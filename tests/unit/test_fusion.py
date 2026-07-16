"""Reciprocal Rank Fusion behavior."""

from graphrag.retrieval.fusion import reciprocal_rank_fusion


def test_rrf_rewards_agreement(make_chunk):
    # 'a' appears near the top of both lists -> should win.
    list1 = [make_chunk("a"), make_chunk("b"), make_chunk("c")]
    list2 = [make_chunk("a"), make_chunk("d")]
    fused = reciprocal_rank_fusion([list1, list2])
    assert fused[0].chunk_id == "a"


def test_rrf_deduplicates(make_chunk):
    fused = reciprocal_rank_fusion([[make_chunk("a")], [make_chunk("a")]])
    ids = [c.chunk_id for c in fused]
    assert ids == ["a"]


def test_rrf_empty():
    assert reciprocal_rank_fusion([[], []]) == []
