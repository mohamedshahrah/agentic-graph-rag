"""Reciprocal Rank Fusion (RRF). Merges several ranked lists into one without
needing comparable scores — ideal for combining vector, graph, and keyword hits."""

from __future__ import annotations

from graphrag.core.types import RetrievedChunk


def reciprocal_rank_fusion(
    result_lists: list[list[RetrievedChunk]], k: int = 60
) -> list[RetrievedChunk]:
    scores: dict[str, float] = {}
    best: dict[str, RetrievedChunk] = {}
    for results in result_lists:
        for rank, chunk in enumerate(results):
            scores[chunk.chunk_id] = scores.get(chunk.chunk_id, 0.0) + 1.0 / (k + rank + 1)
            # Keep one representative per chunk; prefer the first seen.
            best.setdefault(chunk.chunk_id, chunk)

    fused: list[RetrievedChunk] = []
    for chunk_id, score in sorted(scores.items(), key=lambda kv: kv[1], reverse=True):
        chunk = best[chunk_id]
        fused.append(
            RetrievedChunk(
                chunk_id=chunk.chunk_id, text=chunk.text, source=chunk.source,
                score=score, retriever="hybrid", metadata=chunk.metadata,
            )
        )
    return fused
