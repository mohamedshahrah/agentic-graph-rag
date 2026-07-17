"""Graph-augmented retrieval: find the entities a query is about, then pull the
chunks that mention them *and their graph neighborhood*, scored by how many hops
an entity sits from a seed. This is what makes it *graph* RAG rather than plain
vector RAG — it follows relationships, not just similarity."""

from __future__ import annotations

from graphrag.core.types import RetrievedChunk
from graphrag.retrieval.base import Retriever
from graphrag.storage.graph.base import GraphStore


class GraphAugmentedRetriever(Retriever):
    def __init__(self, graph: GraphStore, hops: int = 2) -> None:
        self._graph = graph
        self._hops = hops

    def retrieve(self, query: str, k: int) -> list[RetrievedChunk]:
        seeds = self._graph.fulltext_entities(query, k=5)
        if not seeds:
            return []
        return self._graph.expand_chunks(seeds, hops=self._hops, limit=k)
