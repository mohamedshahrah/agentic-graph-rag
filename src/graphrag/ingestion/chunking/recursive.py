"""Recursive chunker (the default). Splits on structure (paragraphs, lines,
sentences) using a token-aware length function, then hard-caps any oversized
piece with token windowing so nothing exceeds the embedder limit."""

from __future__ import annotations

from langchain_text_splitters import RecursiveCharacterTextSplitter

from graphrag.core.types import Chunk, Document
from graphrag.ingestion.chunking.base import Chunker
from graphrag.ingestion.chunking.token import TokenChunker
from graphrag.ingestion.chunking.tokenizer import TokenCounter


class RecursiveChunker(Chunker):
    def __init__(
        self, counter: TokenCounter, max_tokens: int, overlap: int, tokenizer=None
    ) -> None:
        self._max = max_tokens
        self._counter = counter
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=max_tokens,
            chunk_overlap=overlap,
            length_function=counter.count,
            separators=["\n\n", "\n", ". ", "? ", "! ", "; ", ", ", " ", ""],
        )
        # Fallback hard-splitter for any oversized piece (only if a real tokenizer exists).
        self._hard = (
            TokenChunker(tokenizer, max_tokens, overlap) if tokenizer is not None else None
        )

    def chunk(self, document: Document) -> list[Chunk]:
        pieces = self._splitter.split_text(document.content)
        final: list[str] = []
        for piece in pieces:
            if self._counter.count(piece) <= self._max or self._hard is None:
                final.append(piece)
            else:
                sub = self._hard.chunk(Document(source=document.source, content=piece))
                final.extend(c.text for c in sub)
        return self._emit(document, final)
