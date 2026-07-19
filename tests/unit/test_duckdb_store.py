"""The DuckDB vector store — per-user database file, exact cosine scan."""

from __future__ import annotations

import pytest

from graphrag.core.errors import StorageError
from graphrag.core.types import Chunk
from graphrag.storage.vector.duckdb_store import DuckDBVectorStore, close_all


@pytest.fixture(autouse=True)
def _close_connections():
    yield
    close_all()  # release file handles so tmp_path can be cleaned up


def _chunk(
    doc: str, index: int, vec: list[float] | None, source: str = "doc.pdf", text: str = "body"
) -> Chunk:
    return Chunk(
        doc_id=doc, index=index, text=text, source=source,
        embedding=vec, metadata={"page": index},
    )


def _store(tmp_path, corpus: str = "alice", **kw) -> DuckDBVectorStore:
    return DuckDBVectorStore(tmp_path, "neo4j", corpus, **kw)


def test_setup_creates_the_tenant_file(tmp_path):
    s = _store(tmp_path)
    s.setup(4)
    assert s.path.exists()
    assert s.path.name == "alice.duckdb"


def test_upsert_then_query_ranks_by_cosine(tmp_path):
    s = _store(tmp_path)
    s.setup(4)
    exact = _chunk("d", 0, [1.0, 0.0, 0.0, 0.0], text="exact")
    close = _chunk("d", 1, [0.9, 0.1, 0.0, 0.0], text="close")
    far = _chunk("d", 2, [0.0, 1.0, 0.0, 0.0], text="far")
    s.upsert([exact, close, far])
    hits = s.query([1.0, 0.0, 0.0, 0.0], k=2)
    assert [h.text for h in hits] == ["exact", "close"]
    assert hits[0].chunk_id == exact.id
    assert hits[0].score == pytest.approx(1.0, abs=1e-6)
    assert hits[0].retriever == "vector"


def test_round_trips_text_source_and_metadata(tmp_path):
    s = _store(tmp_path)
    s.setup(2)
    s.upsert([_chunk("d", 3, [1.0, 0.0], source="report.pdf", text="hello world")])
    hit = s.query([1.0, 0.0], k=1)[0]
    assert (hit.text, hit.source, hit.metadata) == ("hello world", "report.pdf", {"page": 3})


def test_upsert_replaces_the_same_chunk(tmp_path):
    """Re-ingesting a document must update rows, not duplicate them."""
    s = _store(tmp_path)
    s.setup(2)
    s.upsert([_chunk("d", 0, [1.0, 0.0], text="old")])
    s.upsert([_chunk("d", 0, [0.0, 1.0], text="new")])
    assert s.count() == 1
    assert s.query([0.0, 1.0], k=1)[0].text == "new"


def test_query_on_an_empty_store_returns_nothing(tmp_path):
    assert _store(tmp_path).query([1.0, 0.0], k=5) == []


def test_delete_source_removes_only_that_document(tmp_path):
    s = _store(tmp_path)
    s.setup(2)
    s.upsert([
        _chunk("keep", 0, [1.0, 0.0], source="keep.pdf"),
        _chunk("drop", 0, [0.0, 1.0], source="drop.pdf"),
        _chunk("drop", 1, [0.5, 0.5], source="drop.pdf"),
    ])
    assert s.delete_source("drop.pdf") == 2
    assert s.count() == 1
    assert {h.source for h in s.query([1.0, 0.0], k=5)} == {"keep.pdf"}


def test_delete_unknown_source_is_a_noop(tmp_path):
    s = _store(tmp_path)
    s.setup(2)
    s.upsert([_chunk("d", 0, [1.0, 0.0])])
    assert s.delete_source("never-ingested.pdf") == 0
    assert s.count() == 1


def test_dimension_change_is_refused(tmp_path):
    """A silent mismatch would surface only as quietly broken retrieval."""
    _store(tmp_path).setup(4)
    close_all()
    with pytest.raises(StorageError, match="4-dim"):
        _store(tmp_path).setup(8)


def test_setup_is_idempotent(tmp_path):
    s = _store(tmp_path)
    s.setup(4)
    s.upsert([_chunk("d", 0, [1.0, 0.0, 0.0, 0.0])])
    s.setup(4)
    assert s.count() == 1  # re-setup must not drop data


def test_tenants_cannot_see_each_other(tmp_path):
    """The isolation guarantee: separate files, no shared rows."""
    alice, bob = _store(tmp_path, "alice"), _store(tmp_path, "bob")
    alice.setup(2)
    bob.setup(2)
    alice.upsert([_chunk("d", 0, [1.0, 0.0], source="alice-only.pdf")])
    assert bob.query([1.0, 0.0], k=10) == []
    assert bob.count() == 0
    assert alice.count() == 1


def test_chunks_without_embeddings_are_skipped(tmp_path):
    s = _store(tmp_path)
    s.setup(2)
    s.upsert([_chunk("d", 0, None)])
    assert s.count() == 0


def test_euclidean_similarity_ranks_nearest_first(tmp_path):
    s = _store(tmp_path, similarity="euclidean")
    s.setup(2)
    s.upsert([_chunk("d", 0, [1.0, 1.0], text="near"), _chunk("d", 1, [9.0, 9.0], text="far")])
    assert [h.text for h in s.query([1.0, 1.1], k=2)] == ["near", "far"]


def test_data_survives_reopening_the_file(tmp_path):
    s = _store(tmp_path)
    s.setup(2)
    s.upsert([_chunk("d", 0, [1.0, 0.0])])
    close_all()
    assert _store(tmp_path).count() == 1


def test_upsert_without_setup_infers_the_dimension(tmp_path):
    s = _store(tmp_path)
    s.upsert([_chunk("d", 0, [1.0, 0.0, 0.0])])
    assert s.count() == 1
    assert len(s.query([1.0, 0.0, 0.0], k=1)) == 1
