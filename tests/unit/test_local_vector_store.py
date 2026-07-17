"""The file-backed vector store: roundtrip, re-ingest replace, and deletion."""

from __future__ import annotations

import pytest

from graphrag.core.errors import StorageError
from graphrag.core.types import Chunk
from graphrag.storage.vector.local_store import LocalVectorStore


def _chunk(doc: str, index: int, text: str, vec: list[float]) -> Chunk:
    c = Chunk(doc_id=doc, index=index, text=text, source=f"{doc}.md")
    c.embedding = vec
    return c


@pytest.fixture
def store(tmp_path) -> LocalVectorStore:
    s = LocalVectorStore(tmp_path, "neo4j", "alice")
    s.setup(3)
    return s


def test_roundtrip_ranks_by_cosine(store):
    store.upsert(
        [
            _chunk("a", 0, "about cats", [1.0, 0.0, 0.0]),
            _chunk("a", 1, "about dogs", [0.0, 1.0, 0.0]),
        ]
    )
    hits = store.query([0.9, 0.1, 0.0], k=2)
    assert [h.text for h in hits] == ["about cats", "about dogs"]
    assert hits[0].score > hits[1].score


def test_upsert_replaces_same_id(store):
    store.upsert([_chunk("a", 0, "old", [1.0, 0.0, 0.0])])
    store.upsert([_chunk("a", 0, "new", [0.0, 0.0, 1.0])])
    hits = store.query([0.0, 0.0, 1.0], k=5)
    assert len(hits) == 1
    assert hits[0].text == "new"


def test_delete_source(store):
    store.upsert(
        [
            _chunk("a", 0, "keep", [1.0, 0.0, 0.0]),
            _chunk("b", 0, "drop", [0.0, 1.0, 0.0]),
        ]
    )
    assert store.delete_source("b.md") == 1
    hits = store.query([0.0, 1.0, 0.0], k=5)
    assert [h.text for h in hits] == ["keep"]


def test_dimension_mismatch_is_loud(store, tmp_path):
    store.upsert([_chunk("a", 0, "x", [1.0, 0.0, 0.0])])
    reopened = LocalVectorStore(tmp_path, "neo4j", "alice")
    with pytest.raises(StorageError):
        reopened.setup(1024)


def test_corpora_are_isolated(tmp_path):
    alice = LocalVectorStore(tmp_path, "neo4j", "alice")
    bob = LocalVectorStore(tmp_path, "neo4j", "bob")
    alice.setup(3)
    bob.setup(3)
    alice.upsert([_chunk("a", 0, "alice private", [1.0, 0.0, 0.0])])
    assert bob.query([1.0, 0.0, 0.0], k=5) == []
