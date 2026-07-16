"""Vector store interface — the similarity-search half of the store."""

from __future__ import annotations

import abc

from graphrag.core.types import Chunk, RetrievedChunk


class VectorStore(abc.ABC):
    @abc.abstractmethod
    def setup(self, dim: int) -> None:
        """Create the vector index for the given embedding dimension (idempotent)."""

    @abc.abstractmethod
    def upsert(self, chunks: list[Chunk]) -> None:
        """Store chunk nodes with their embeddings."""

    @abc.abstractmethod
    def query(self, vector: list[float], k: int) -> list[RetrievedChunk]:
        ...
