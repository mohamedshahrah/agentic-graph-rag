"""Embedder interface. All embedding providers implement this."""

from __future__ import annotations

import abc


class Embedder(abc.ABC):
    """Turns text into vectors. Documents and queries can be embedded differently
    (some models want a 'query:' / 'passage:' prefix), which is why they are
    separate methods."""

    #: Output dimensionality. Providers set this at init.
    dim: int = 0

    @abc.abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        ...

    @abc.abstractmethod
    def embed_query(self, text: str) -> list[float]:
        ...
