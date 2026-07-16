"""Pure vector retrieval: embed the query, ask the vector store for nearest chunks."""

from __future__ import annotations

from graphrag.core.types import RetrievedChunk
from graphrag.embeddings.base import Embedder
from graphrag.retrieval.base import Retriever
from graphrag.storage.vector.base import VectorStore


class VectorRetriever(Retriever):
    def __init__(self, embedder: Embedder, store: VectorStore) -> None:
        self._embedder = embedder
        self._store = store

    def retrieve(self, query: str, k: int) -> list[RetrievedChunk]:
        vector = self._embedder.embed_query(query)
        return self._store.query(vector, k)
