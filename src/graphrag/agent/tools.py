"""The agent's tools. Each is a real capability over the store, not a wrapper
around one vector call — that's what makes this an *agentic* graph RAG: the model
chooses among genuinely different retrieval strategies.

Tools return text for the model to read, and also record the chunks they surfaced
into a shared collector so the API can report exact sources.

Everything a tool returns is document-derived and therefore untrusted: chunk
text obviously, but also entity names, descriptions, and community summaries —
those were extracted *by an LLM from user documents* and can carry injected
instructions just as easily. So every output is sanitized and wrapped in the
untrusted-data envelope the system prompt tells the model to treat as data only,
and capped so a hostile document can't flood the context."""

from __future__ import annotations

from dataclasses import dataclass, field

from langchain_core.tools import StructuredTool

from graphrag.agent.prompts import wrap_untrusted
from graphrag.core.sanitize import sanitize_untrusted
from graphrag.core.types import RetrievedChunk
from graphrag.embeddings.base import Embedder
from graphrag.retrieval.hybrid import HybridRetriever
from graphrag.retrieval.vector import VectorRetriever
from graphrag.storage.graph.base import GraphStore

_MAX_CHUNK_CHARS = 4000
_MAX_TOOL_OUTPUT_CHARS = 8000


@dataclass
class ToolContext:
    """Shared state the tools read from and write into for one query."""

    vector: VectorRetriever
    hybrid: HybridRetriever
    graph: GraphStore
    embedder: Embedder
    top_k: int = 8
    graph_hops: int = 2
    collected: list[RetrievedChunk] = field(default_factory=list)


def _src(source: str) -> str:
    """Source names come from uploaded filenames — sanitize and keep them to
    one attribute-safe line."""
    return sanitize_untrusted(source, 200).replace('"', "'").replace("\n", " ")


def _cap(text: str) -> str:
    if len(text) > _MAX_TOOL_OUTPUT_CHARS:
        return text[:_MAX_TOOL_OUTPUT_CHARS] + " …[truncated]"
    return text


def _format(chunks: list[RetrievedChunk]) -> str:
    if not chunks:
        return "No results."
    # The [source: ...] tag stays outside the envelope: it is ours (the model
    # cites it), while the text inside the markers is the document's.
    return _cap(
        "\n\n".join(
            f"[source: {_src(c.source)}]\n"
            + wrap_untrusted(_src(c.source), sanitize_untrusted(c.text.strip(), _MAX_CHUNK_CHARS))
            for c in chunks
        )
    )


def _graph_data(text: str) -> str:
    """Wrap graph-derived text (entity names/descriptions extracted from user
    documents by an LLM — untrusted like everything else)."""
    return _cap(wrap_untrusted("knowledge-graph", sanitize_untrusted(text, _MAX_TOOL_OUTPUT_CHARS)))


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
        return _graph_data(ctx.graph.neighbors(entity, ctx.graph_hops))

    def expand_subgraph(entities: str) -> str:
        """Explore the graph around several entities at once. Pass a comma-separated
        list of entity names."""
        names = [e.strip() for e in entities.split(",") if e.strip()]
        parts = [ctx.graph.neighbors(name, ctx.graph_hops) for name in names]
        chunks = ctx.graph.chunks_for_entities(names, limit=ctx.top_k)
        _collect(ctx, chunks)
        return _cap(_graph_data("\n\n".join(parts)) + "\n\n" + _format(chunks))

    def get_entity(name: str) -> str:
        """Look up what the graph knows about a single entity: its type, description,
        and directly connected entities."""
        info = ctx.graph.get_entity(name)
        if not info:
            return f"No entity named '{sanitize_untrusted(name, 200)}' found."
        return _graph_data(
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
        return _cap("\n\n".join(blocks))

    def global_search(question: str) -> str:
        """Answer corpus-wide questions ('what are the main themes?', 'give an
        overview') from community summaries of the whole knowledge graph. Use when
        the question is about the collection as a whole, not one specific fact."""
        from graphrag.ingestion.enrich import global_search as _global

        return _cap(
            wrap_untrusted(
                "community-summaries",
                sanitize_untrusted(
                    _global(ctx.graph, ctx.embedder, question), _MAX_TOOL_OUTPUT_CHARS
                ),
            )
        )

    return [
        StructuredTool.from_function(hybrid_search),
        StructuredTool.from_function(vector_search),
        StructuredTool.from_function(graph_neighbors),
        StructuredTool.from_function(expand_subgraph),
        StructuredTool.from_function(get_entity),
        StructuredTool.from_function(fulltext_search),
        StructuredTool.from_function(compare),
        StructuredTool.from_function(global_search),
    ]
