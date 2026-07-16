"""Agent package. Heavy imports (LangGraph) are loaded lazily so lightweight
submodules like `graphrag.agent.styles` can be imported on their own."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from graphrag.agent.graph import AgentRunner, AgentSession, build_checkpointer

__all__ = ["AgentRunner", "AgentSession", "build_checkpointer"]


def __getattr__(name: str):  # PEP 562 lazy attribute loading
    if name in __all__:
        from graphrag.agent import graph

        return getattr(graph, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
