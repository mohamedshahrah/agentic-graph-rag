"""The agent's tools. Each is a real capability over the store, not a wrapper
around one vector call — that's what makes this an *agentic* graph RAG: the model
chooses among genuinely different retrieval strategies.

Tools return text for the model to read, and also record the chunks they surfaced
into a shared collector so the API can report exact sources."""

from __future__ import annotations

from dataclasses import dataclass, field

from langchain_core.tools import StructuredTool

from graphrag.core.types import RetrievedChunk
from graphrag.retrieval.hybrid import HybridRetriever
from graphrag.retrieval.vector import VectorRetriever
from graphrag.storage.graph.base import GraphStore


@dataclass
class ToolContext:
    """Shared state the tools read from and write into for one query."""

    vector: VectorRetriever
    hybrid: HybridRetriever
    graph: GraphStore
    top_k: int = 8
    graph_hops: int = 2
    collected: list[RetrievedChunk] = field(default_factory=list)


def _format(chunks: list[RetrievedChunk]) -> str:
    if not chunks:
        return "No results."
    return "\n\n".join(
        f"[source: {c.source}]\n{c.text.strip()}" for c in chunks
    )


def _collect(ctx: ToolContext, chunks: list[RetrievedChunk]) -> None:
    seen = {c.chunk_id for c in ctx.collected}
    ctx.collected.extend(c for c in chunks if c.chunk_id not in seen)


def build_tools(ctx: ToolContext) -> list[StructuredTool]:
    def hybrid_search(query: str) -> str:
        """Search the knowledge base with the strong hybrid retriever (vector +
        graph + keyword, reranked). Use this for most questions."""
        chunks = ctx.hybrid.retrieve(query, ctx.top_k)
        _collect(ctx, chunks)
        return _format(chunks)

    def vector_search(query: str) -> str:
        """Semantic similarity search over text chunks. Use to find passages about a topic."""
        chunks = ctx.vector.retrieve(query, ctx.top_k)
        _collect(ctx, chunks)
        return _format(chunks)

    def graph_neighbors(entity: str) -> str:
        """List the relationships around one entity in the knowledge graph. Use for
        'how is X connected?' questions."""
        return ctx.graph.neighbors(entity, ctx.graph_hops)

    def expand_subgraph(entities: str) -> str:
        """Explore the graph around several entities at once. Pass a comma-separated
        list of entity names."""
        names = [e.strip() for e in entities.split(",") if e.strip()]
        parts = [ctx.graph.neighbors(name, ctx.graph_hops) for name in names]
        chunks = ctx.graph.chunks_for_entities(names, limit=ctx.top_k)
        _collect(ctx, chunks)
        return "\n\n".join(parts) + "\n\n" + _format(chunks)

    def get_entity(name: str) -> str:
        """Look up what the graph knows about a single entity: its type, description,
        and directly connected entities."""
        info = ctx.graph.get_entity(name)
        if not info:
            return f"No entity named '{name}' found."
        return (
            f"{info['name']} ({info['type']})\n{info.get('description', '')}\n"
            f"Connected to: {', '.join(info.get('connected', []))}"
        )

    def fulltext_search(text: str) -> str:
        """Exact keyword search over chunks. Use when you know a specific term."""
        chunks = ctx.graph.fulltext_chunks(text, ctx.top_k)
        _collect(ctx, chunks)
        return _format(chunks)

    def compare(subjects: str) -> str:
        """Gather evidence about several subjects for a side-by-side comparison.
        Pass a comma-separated list of subjects (e.g. 'Postgres, MySQL')."""
        names = [s.strip() for s in subjects.split(",") if s.strip()]
        blocks = []
        for name in names:
            chunks = ctx.hybrid.retrieve(name, max(3, ctx.top_k // 2))
            _collect(ctx, chunks)
            blocks.append(f"### {name}\n{_format(chunks)}")
        return "\n\n".join(blocks)

    return [
        StructuredTool.from_function(hybrid_search),
        StructuredTool.from_function(vector_search),
        StructuredTool.from_function(graph_neighbors),
        StructuredTool.from_function(expand_subgraph),
        StructuredTool.from_function(get_entity),
        StructuredTool.from_function(fulltext_search),
        StructuredTool.from_function(compare),
    ]
