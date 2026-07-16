"""Semantic chunker (opt-in quality mode). Embeds sentences, then starts a new
chunk wherever consecutive sentences drift apart in meaning (cosine distance
above a threshold). Bounded by min/max token sizes."""

from __future__ import annotations

import re

from graphrag.core.types import Chunk, Document
from graphrag.embeddings.base import Embedder
from graphrag.ingestion.chunking.base import Chunker
from graphrag.ingestion.chunking.tokenizer import TokenCounter

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _cosine_distance(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 1.0
    return 1.0 - dot / (na * nb)


class SemanticChunker(Chunker):
    def __init__(
        self,
        embedder: Embedder,
        counter: TokenCounter,
        threshold: float,
        max_tokens: int,
        min_tokens: int,
    ) -> None:
        self._embedder = embedder
        self._counter = counter
        self._threshold = threshold
        self._max = max_tokens
        self._min = min_tokens

    def chunk(self, document: Document) -> list[Chunk]:
        sentences = [s.strip() for s in _SENT_SPLIT.split(document.content) if s.strip()]
        if len(sentences) <= 1:
            return self._emit(document, sentences)

        vectors = self._embedder.embed_documents(sentences)
        chunks: list[str] = []
        current: list[str] = [sentences[0]]
        current_tokens = self._counter.count(sentences[0])

        for i in range(1, len(sentences)):
            dist = _cosine_distance(vectors[i - 1], vectors[i])
            sent_tokens = self._counter.count(sentences[i])
            boundary = dist > self._threshold and current_tokens >= self._min
            too_big = current_tokens + sent_tokens > self._max
            if boundary or too_big:
                chunks.append(" ".join(current))
                current, current_tokens = [sentences[i]], sent_tokens
            else:
                current.append(sentences[i])
                current_tokens += sent_tokens
        if current:
            chunks.append(" ".join(current))
        return self._emit(document, chunks)
