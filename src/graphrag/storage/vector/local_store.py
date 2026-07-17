"""File-backed vector store: exact cosine/euclidean search over numpy arrays.

No service, no new dependency — vectors live in `data/vectors/` as an .npz plus
a JSON sidecar per (database, corpus). Exact search is O(n) per query, which is
the right trade until a corpus outgrows ~10^5 chunks; past that, swap in a real
ANN backend behind the same `VectorStore` interface.

Chunk *nodes* still live in Neo4j (fulltext + MENTIONS need them); this backend
only replaces where the embeddings sit. Single-writer by design: the ingest
worker writes, the API reloads on file change.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import numpy as np

from graphrag.core.errors import StorageError
from graphrag.core.types import Chunk, RetrievedChunk
from graphrag.storage.vector.base import VectorStore


class LocalVectorStore(VectorStore):
    def __init__(
        self, root: str | Path, database: str, corpus: str, similarity: str = "cosine"
    ) -> None:
        safe_corpus = corpus.replace("/", "_").replace("\\", "_")
        base = Path(root) / database
        self._vec_path = base / f"{safe_corpus}.npz"
        self._meta_path = base / f"{safe_corpus}.json"
        self._cosine = similarity != "euclidean"
        self._lock = threading.Lock()
        self._loaded_mtime: float | None = None
        self._ids: list[str] = []
        self._vectors = np.zeros((0, 0), dtype=np.float32)
        self._rows: dict[str, dict] = {}  # id -> {text, source, metadata}
        self._dim: int | None = None

    # -- persistence ----------------------------------------------------------
    def _load(self) -> None:
        if not self._vec_path.exists():
            return
        mtime = self._vec_path.stat().st_mtime
        if self._loaded_mtime == mtime:
            return
        with np.load(self._vec_path, allow_pickle=False) as data:
            self._ids = [str(i) for i in data["ids"]]
            self._vectors = data["vectors"].astype(np.float32)
        self._rows = json.loads(self._meta_path.read_text(encoding="utf-8"))
        self._dim = self._vectors.shape[1] if self._vectors.size else self._dim
        self._loaded_mtime = mtime

    def _save(self) -> None:
        self._vec_path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            self._vec_path, ids=np.array(self._ids, dtype=str), vectors=self._vectors
        )
        self._meta_path.write_text(json.dumps(self._rows), encoding="utf-8")
        self._loaded_mtime = self._vec_path.stat().st_mtime

    # -- VectorStore ----------------------------------------------------------
    def setup(self, dim: int) -> None:
        with self._lock:
            self._load()
            if self._dim is not None and self._dim != int(dim):
                raise StorageError(
                    f"Vector store at {self._vec_path} holds {self._dim}-dim vectors "
                    f"but the embedder produces {dim}. Delete the store and re-ingest."
                )
            self._dim = int(dim)

    def upsert(self, chunks: list[Chunk]) -> None:
        rows = [c for c in chunks if c.embedding is not None]
        if not rows:
            return
        with self._lock:
            self._load()
            if self._vectors.size == 0:
                self._vectors = np.zeros((0, len(rows[0].embedding)), dtype=np.float32)
            index = {cid: i for i, cid in enumerate(self._ids)}
            appended: list[np.ndarray] = []
            for c in rows:
                vec = np.asarray(c.embedding, dtype=np.float32)
                self._rows[c.id] = {
                    "text": c.text, "source": c.source, "metadata": c.metadata or {}
                }
                if c.id in index:
                    self._vectors[index[c.id]] = vec
                else:
                    index[c.id] = len(self._ids)
                    self._ids.append(c.id)
                    appended.append(vec)
            if appended:
                self._vectors = np.vstack([self._vectors, np.stack(appended)])
            self._save()

    def query(self, vector: list[float], k: int) -> list[RetrievedChunk]:
        with self._lock:
            self._load()
            if not self._ids:
                return []
            q = np.asarray(vector, dtype=np.float32)
            if self._cosine:
                vn = self._vectors / np.clip(
                    np.linalg.norm(self._vectors, axis=1, keepdims=True), 1e-12, None
                )
                qn = q / max(float(np.linalg.norm(q)), 1e-12)
                scores = vn @ qn
            else:
                scores = -np.linalg.norm(self._vectors - q, axis=1)
            top = np.argsort(scores)[::-1][:k]
            out = []
            for i in top:
                cid = self._ids[int(i)]
                row = self._rows.get(cid, {})
                out.append(
                    RetrievedChunk(
                        chunk_id=cid,
                        text=row.get("text", ""),
                        source=row.get("source", ""),
                        score=float(scores[int(i)]),
                        retriever="vector",
                        metadata=row.get("metadata", {}) or {},
                    )
                )
            return out

    def delete_source(self, source: str) -> int:
        with self._lock:
            self._load()
            keep = [
                i for i, cid in enumerate(self._ids)
                if self._rows.get(cid, {}).get("source") != source
            ]
            removed = len(self._ids) - len(keep)
            if removed:
                self._vectors = self._vectors[keep] if keep else np.zeros(
                    (0, self._vectors.shape[1] if self._vectors.size else 0),
                    dtype=np.float32,
                )
                kept_ids = [self._ids[i] for i in keep]
                for cid in set(self._ids) - set(kept_ids):
                    self._rows.pop(cid, None)
                self._ids = kept_ids
                self._save()
            return removed
