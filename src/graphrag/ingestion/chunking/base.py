"""Chunker interface: a Document -> ordered list of Chunks."""

from __future__ import annotations

import abc

from graphrag.core.types import Chunk, Document


class Chunker(abc.ABC):
    @abc.abstractmethod
    def chunk(self, document: Document) -> list[Chunk]:
        ...

    @staticmethod
    def _emit(document: Document, texts: list[str]) -> list[Chunk]:
        chunks: list[Chunk] = []
        for i, text in enumerate(t for t in texts if t.strip()):
            chunks.append(
                Chunk(
                    doc_id=document.id,
                    index=i,
                    text=text,
                    source=document.source,
                    metadata=dict(document.metadata),
                )
            )
        return chunks
