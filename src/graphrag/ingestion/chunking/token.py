"""Token-window chunker — the literal 'encode / decode' strategy.

    encode(text) -> token ids -> slide a fixed window (with overlap) -> decode

Guarantees every chunk fits the embedder's max sequence length. Deterministic
and cheap, but may cut mid-sentence — use `recursive` for nicer boundaries.
"""

from __future__ import annotations

from graphrag.core.errors import ConfigError
from graphrag.core.types import Chunk, Document
from graphrag.ingestion.chunking.base import Chunker


class TokenChunker(Chunker):
    def __init__(self, tokenizer, max_tokens: int, overlap: int) -> None:
        if tokenizer is None:
            raise ConfigError(
                "The 'token' chunking strategy needs a HuggingFace tokenizer. "
                "Use a local embedder, or switch chunking.strategy to 'recursive'."
            )
        if overlap >= max_tokens:
            raise ConfigError("chunking.overlap must be smaller than chunking.max_tokens")
        self._tok = tokenizer
        self._max = max_tokens
        self._stride = max_tokens - overlap

    def chunk(self, document: Document) -> list[Chunk]:
        ids = self._tok.encode(document.content, add_special_tokens=False)
        windows: list[str] = []
        for start in range(0, len(ids), self._stride):
            window_ids = ids[start : start + self._max]
            if not window_ids:
                break
            windows.append(self._tok.decode(window_ids))
            if start + self._max >= len(ids):
                break
        return self._emit(document, windows)
