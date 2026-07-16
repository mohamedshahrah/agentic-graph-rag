"""Hybrid retriever: run vector + graph-augmented + keyword search, fuse the
rankings with RRF, then rerank the fused candidates. This is the strong default
the agent's `hybrid_search` tool calls."""

from __future__ import annotations

from graphrag.core.types import RetrievedChunk
from graphrag.retrieval.base import Retriever
from graphrag.retrieval.fusion import reciprocal_rank_fusion
from graphrag.retrieval.graph_augmented import GraphAugmentedRetriever
from graphrag.retrieval.reranker import Reranker
from graphrag.retrieval.vector import VectorRetriever
from graphrag.storage.graph.base import GraphStore


class HybridRetriever(Retriever):
    def __init__(
        self,
        vector: VectorRetriever,
        graph_aug: GraphAugmentedRetriever,
        graph: GraphStore,
        reranker: Reranker,
        candidate_k: int = 24,
    ) -> None:
        self._vector = vector
        self._graph_aug = graph_aug
        self._graph = graph
        self._reranker = reranker
        self._candidate_k = candidate_k

    def retrieve(self, query: str, k: int) -> list[RetrievedChunk]:
        lists: list[list[RetrievedChunk]] = [
            self._vector.retrieve(query, self._candidate_k),
            self._graph_aug.retrieve(query, self._candidate_k),
            self._graph.fulltext_chunks(query, self._candidate_k),
        ]
        fused = reciprocal_rank_fusion(lists)[: self._candidate_k]
        return self._reranker.rerank(query, fused, k)
