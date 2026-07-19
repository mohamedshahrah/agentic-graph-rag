"""DuckDB vector store: one embedded database file per user.

Where `local_store` keeps every corpus in numpy files, this gives each tenant a
real database file — `{duckdb_dir}/{database}/{corpus}.duckdb`. That is the
isolation boundary: a user's vectors are a separate file that can be backed up,
inspected, or deleted on its own, and a query physically cannot reach another
tenant's rows.

Search is an exact cosine scan (`array_cosine_similarity` over a fixed-width
FLOAT[dim] column), not an ANN index. At the per-user chunk ceiling the quota
system enforces (~20k), a scan is single-digit milliseconds and always exact;
DuckDB's HNSW extension still carries experimental persistence, which is a poor
trade for recall we don't need.

**Single-process ownership.** DuckDB takes an exclusive lock on an open file, so
exactly one OS process may hold a given tenant's database. The deployment
satisfies this by running ingest inside the API process (uvicorn workers=1)
rather than in a separate worker container. Within the process, connections are
cached per file and writes serialize on a per-file lock; reads use cursors off
the same connection, which DuckDB handles concurrently under MVCC.
"""

from __future__ import annotations

import contextlib
import json
import threading
from pathlib import Path

from graphrag.core.errors import StorageError
from graphrag.core.types import Chunk, RetrievedChunk
from graphrag.storage.vector.base import VectorStore

# One connection per database file, shared process-wide. Opening a second
# connection to the same file from another *process* is what DuckDB refuses;
# within this process a single connection is both required and sufficient.
_CONNECTIONS: dict[Path, object] = {}
_LOCKS: dict[Path, threading.Lock] = {}
_REGISTRY_LOCK = threading.Lock()


def _connect(path: Path, memory_limit_mb: int):
    """Get (or open) the process-wide connection for `path`."""
    with _REGISTRY_LOCK:
        conn = _CONNECTIONS.get(path)
        if conn is not None:
            return conn, _LOCKS[path]
        try:
            import duckdb
        except ImportError as exc:  # pragma: no cover
            raise StorageError(
                "The duckdb vector provider needs the `duckdb` package."
            ) from exc
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = duckdb.connect(str(path))
        # Bound per-tenant memory and keep DuckDB from fanning out across the
        # box's few cores — retrieval is latency-bound, and the API is serving
        # other requests on the same two vCPUs.
        conn.execute(f"PRAGMA memory_limit='{max(64, memory_limit_mb)}MB'")
        conn.execute("PRAGMA threads=1")
        _CONNECTIONS[path] = conn
        _LOCKS[path] = threading.Lock()
        return conn, _LOCKS[path]


def close_all() -> None:
    """Close every open database file. Used on shutdown and after a tenant purge
    (the file cannot be deleted on Windows while a handle is open)."""
    with _REGISTRY_LOCK:
        for conn in _CONNECTIONS.values():
            with contextlib.suppress(Exception):  # shutdown is best effort
                conn.close()
        _CONNECTIONS.clear()
        _LOCKS.clear()


def close_file(path: Path) -> None:
    """Release one tenant's database file."""
    with _REGISTRY_LOCK:
        conn = _CONNECTIONS.pop(path, None)
        _LOCKS.pop(path, None)
    if conn is not None:
        with contextlib.suppress(Exception):
            conn.close()


class DuckDBVectorStore(VectorStore):
    def __init__(
        self,
        root: str | Path,
        database: str,
        corpus: str,
        similarity: str = "cosine",
        memory_limit_mb: int = 256,
    ) -> None:
        safe_corpus = corpus.replace("/", "_").replace("\\", "_")
        self.path = Path(root) / database / f"{safe_corpus}.duckdb"
        self._cosine = similarity != "euclidean"
        self._memory_limit_mb = memory_limit_mb
        self._dim: int | None = None

    # -- helpers --------------------------------------------------------------
    def _conn(self):
        return _connect(self.path, self._memory_limit_mb)

    def _stored_dim(self, cur) -> int | None:
        """Read the embedding width back out of the table definition."""
        rows = cur.execute(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = 'chunks' AND column_name = 'embedding'"
        ).fetchall()
        if not rows:
            return None
        # data_type looks like 'FLOAT[1024]'
        text = str(rows[0][0])
        digits = "".join(ch for ch in text if ch.isdigit())
        return int(digits) if digits else None

    def _score_expr(self) -> str:
        # Euclidean distance is smaller-is-better; negate so callers can always
        # sort descending and compare scores across retrievers.
        if self._cosine:
            return "array_cosine_similarity(embedding, ?::FLOAT[{dim}])"
        return "-array_distance(embedding, ?::FLOAT[{dim}])"

    # -- VectorStore ----------------------------------------------------------
    def setup(self, dim: int) -> None:
        dim = int(dim)
        conn, lock = self._conn()
        with lock:
            cur = conn.cursor()
            existing = self._stored_dim(cur)
            if existing is not None and existing != dim:
                # Fixed-width arrays make a dimension change a hard error rather
                # than a silent mismatch that only shows up as bad retrieval.
                raise StorageError(
                    f"Vector store at {self.path} holds {existing}-dim vectors but the "
                    f"embedder produces {dim}. Delete the file and re-ingest."
                )
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS chunks (
                    id       TEXT PRIMARY KEY,
                    source   TEXT,
                    text     TEXT,
                    metadata TEXT,
                    embedding FLOAT[{dim}]
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS chunks_source ON chunks (source)")
            self._dim = dim

    def upsert(self, chunks: list[Chunk]) -> None:
        rows = [c for c in chunks if c.embedding is not None]
        if not rows:
            return
        if self._dim is None:
            self.setup(len(rows[0].embedding))
        conn, lock = self._conn()
        payload = [
            (
                c.id,
                c.source,
                c.text,
                json.dumps(c.metadata or {}),
                [float(x) for x in c.embedding],
            )
            for c in rows
        ]
        with lock:
            cur = conn.cursor()
            # DELETE+INSERT rather than INSERT OR REPLACE: re-ingesting a
            # document must not leave a half-updated row if the insert fails.
            cur.execute("BEGIN TRANSACTION")
            try:
                cur.executemany("DELETE FROM chunks WHERE id = ?", [(c.id,) for c in rows])
                cur.executemany(
                    "INSERT INTO chunks (id, source, text, metadata, embedding) "
                    "VALUES (?, ?, ?, ?, ?)",
                    payload,
                )
                cur.execute("COMMIT")
            except Exception:
                cur.execute("ROLLBACK")
                raise

    def query(self, vector: list[float], k: int) -> list[RetrievedChunk]:
        conn, lock = self._conn()
        with lock:
            cur = conn.cursor()
            if self._dim is None:
                self._dim = self._stored_dim(cur)
                if self._dim is None:
                    return []  # nothing ingested yet
            score = self._score_expr().format(dim=self._dim)
            rows = cur.execute(
                f"SELECT id, source, text, metadata, {score} AS score "
                "FROM chunks WHERE embedding IS NOT NULL "
                "ORDER BY score DESC LIMIT ?",
                [[float(x) for x in vector], int(k)],
            ).fetchall()
        out: list[RetrievedChunk] = []
        for cid, source, text, meta, score_val in rows:
            try:
                metadata = json.loads(meta) if meta else {}
            except (TypeError, ValueError):
                metadata = {}
            out.append(
                RetrievedChunk(
                    chunk_id=cid,
                    text=text or "",
                    source=source or "",
                    score=float(score_val if score_val is not None else 0.0),
                    retriever="vector",
                    metadata=metadata,
                )
            )
        return out

    def delete_source(self, source: str) -> int:
        conn, lock = self._conn()
        with lock:
            cur = conn.cursor()
            if self._stored_dim(cur) is None:
                return 0
            n = cur.execute(
                "SELECT count(*) FROM chunks WHERE source = ?", [source]
            ).fetchone()[0]
            if n:
                cur.execute("DELETE FROM chunks WHERE source = ?", [source])
            return int(n)

    def count(self) -> int:
        """Rows stored for this tenant — the quota system's chunk metric."""
        conn, lock = self._conn()
        with lock:
            cur = conn.cursor()
            if self._stored_dim(cur) is None:
                return 0
            return int(cur.execute("SELECT count(*) FROM chunks").fetchone()[0])

    def close(self) -> None:
        close_file(self.path)
