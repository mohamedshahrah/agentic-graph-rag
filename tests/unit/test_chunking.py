"""Chunking logic that doesn't need a downloaded model (uses the heuristic
token counter, so no network)."""

from graphrag.core.types import Document
from graphrag.ingestion.chunking.recursive import RecursiveChunker
from graphrag.ingestion.chunking.tokenizer import TokenCounter


def _doc(text: str) -> Document:
    return Document(source="test.txt", content=text)


def test_recursive_produces_chunks():
    counter = TokenCounter(None)  # heuristic counter, no tokenizer
    chunker = RecursiveChunker(counter, max_tokens=20, overlap=5)
    text = "First paragraph here.\n\n" + "word " * 200
    chunks = chunker.chunk(_doc(text))
    assert len(chunks) > 1
    assert all(c.text.strip() for c in chunks)


def test_chunk_ids_are_stable_and_ordered():
    counter = TokenCounter(None)
    chunker = RecursiveChunker(counter, max_tokens=20, overlap=5)
    chunks = chunker.chunk(_doc("word " * 100))
    assert [c.index for c in chunks] == list(range(len(chunks)))
    assert len({c.id for c in chunks}) == len(chunks)  # unique ids


def test_empty_document_yields_nothing():
    counter = TokenCounter(None)
    chunker = RecursiveChunker(counter, max_tokens=20, overlap=5)
    assert chunker.chunk(_doc("   ")) == []
