"""Entity resolution and community clustering — the pure logic, no Neo4j."""

from __future__ import annotations

import hashlib

from graphrag.config.settings import EntityResolutionCfg
from graphrag.ingestion.enrich import _contained, _UnionFind, resolve_entities


class _FakeEmbedder:
    """Deterministic embeddings: identical names are identical vectors, and
    different names are near-orthogonal.

    Two details matter. `hashlib`, not `hash()`: the builtin is salted per
    process, so vectors changed between runs. And bytes are centered to
    [-1, 1) rather than kept positive: vectors confined to one octant have a
    cosine similarity around 0.9 by chance, which crossed the 0.93 merge
    threshold on unlucky seeds and merged unrelated entities.
    """

    dim = 16

    def embed_documents(self, texts):
        return [self._vec(t) for t in texts]

    def embed_query(self, text):
        return self._vec(text)

    @staticmethod
    def _vec(text: str):
        digest = hashlib.sha256(text.lower().encode()).digest()
        return [(b - 127.5) / 127.5 for b in digest[:16]]


class _FakeGraph:
    def __init__(self, entities):
        self._entities = entities
        self.merges: list[tuple[str, list[str]]] = []

    def all_entities(self, limit=5000):
        return self._entities[:limit]

    def merge_entities(self, winner, losers):
        self.merges.append((winner, losers))


def test_union_find_groups():
    uf = _UnionFind()
    uf.union("a", "b")
    uf.union("b", "c")
    uf.union("x", "y")
    groups = sorted(sorted(g) for g in uf.groups())
    assert groups == [["a", "b", "c"], ["x", "y"]]


def test_containment_is_token_bounded():
    assert _contained("acme", "acme robotics")
    assert _contained("riverside university", "riverside university lab")
    assert not _contained("ai", "air traffic")  # too short
    assert not _contained("rive", "riverside")  # substring, not a token


def test_resolution_merges_contained_names():
    graph = _FakeGraph(
        [
            {"key": "acme", "name": "Acme", "type": "Org"},
            {"key": "acme robotics", "name": "Acme Robotics", "type": "Org"},
            {"key": "initech", "name": "Initech", "type": "Org"},
        ]
    )
    folded = resolve_entities(graph, _FakeEmbedder(), EntityResolutionCfg())
    assert folded == 1
    assert graph.merges == [("acme robotics", ["acme"])]  # longest name wins


def test_resolution_disabled_is_a_noop():
    graph = _FakeGraph([{"key": "a b", "name": "A B", "type": "T"}] * 2)
    cfg = EntityResolutionCfg(enabled=False)
    assert resolve_entities(graph, _FakeEmbedder(), cfg) == 0
    assert graph.merges == []
