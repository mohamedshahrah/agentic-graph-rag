"""Retriever interface."""

from __future__ import annotations

import abc

from graphrag.core.types import RetrievedChunk


class Retriever(abc.ABC):
    @abc.abstractmethod
    def retrieve(self, query: str, k: int) -> list[RetrievedChunk]:
        ...
