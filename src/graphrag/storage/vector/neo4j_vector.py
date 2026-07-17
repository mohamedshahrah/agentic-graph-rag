"""Neo4j native vector index over :Chunk(embedding). Keeping vectors in the same
database as the graph means one hop to go from a matched chunk to its entities."""

from __future__ import annotations

import json

from graphrag.core.types import Chunk, RetrievedChunk
from graphrag.storage.neo4j_client import safe_ident
from graphrag.storage.vector.base import VectorStore

_SIM = {"cosine": "cosine", "euclidean": "euclidean"}


def _meta(raw) -> dict:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


class Neo4jVectorStore(VectorStore):
    def __init__(
        self, driver, database: str, corpus: str, index_name: str, similarity: str
    ) -> None:
        self._driver = driver
        self._db = database
        self._corpus = corpus
        self._index = safe_ident(index_name)
        self._sim = _SIM.get(similarity, "cosine")

    def _run(self, query: str, **params):
        with self._driver.session(database=self._db) as session:
            return list(session.run(query, corpus=self._corpus, **params))

    def setup(self, dim: int) -> None:
        dim = int(dim)
        self._run(
            f"""
            CREATE VECTOR INDEX {self._index} IF NOT EXISTS
            FOR (c:Chunk) ON (c.embedding)
            OPTIONS {{indexConfig: {{
                `vector.dimensions`: {dim},
                `vector.similarity_function`: '{self._sim}'
            }}}}
            """
        )

    def upsert(self, chunks: list[Chunk]) -> None:
        rows = [
            {
                "id": c.id,
                "doc_id": c.doc_id,
                "text": c.text,
                "source": c.source,
                "embedding": c.embedding,
                "metadata": json.dumps(c.metadata or {}),
            }
            for c in chunks
            if c.embedding is not None
        ]
        self._run(
            # (corpus, id) — never bare id: two tenants ingesting the same file
            # produce identical chunk ids, and a bare-id MERGE would hand one
            # tenant's node to the other.
            """
            UNWIND $rows AS row
            MERGE (c:Chunk {corpus: $corpus, id: row.id})
            SET c.text = row.text, c.source = row.source, c.doc_id = row.doc_id,
                c.embedding = row.embedding, c.metadata = row.metadata
            """,
            rows=rows,
        )

    def query(self, vector: list[float], k: int) -> list[RetrievedChunk]:
        # Over-fetch, then filter by corpus (the index is global to the DB).
        rows = self._run(
            f"""
            CALL db.index.vector.queryNodes('{self._index}', $fetch, $vector)
            YIELD node, score
            WHERE node.corpus = $corpus
            RETURN node.id AS id, node.text AS text, node.source AS source,
                   node.metadata AS metadata, score
            LIMIT $k
            """,
            vector=vector,
            fetch=k * 4,
            k=k,
        )
        return [
            RetrievedChunk(
                chunk_id=r["id"], text=r["text"], source=r["source"],
                score=float(r["score"]), retriever="vector", metadata=_meta(r["metadata"]),
            )
            for r in rows
        ]

    # delete_source: vectors live on the chunk nodes, which
    # GraphStore.delete_document removes — the base no-op is correct here.
