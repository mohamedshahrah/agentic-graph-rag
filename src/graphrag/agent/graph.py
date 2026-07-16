"""The LangGraph agent. Wires the chat model + tools into a ReAct loop with
optional Redis-backed multi-turn memory, and exposes both a blocking `run` and a
token-streaming `astream_tokens`."""

from __future__ import annotations

from collections.abc import AsyncIterator

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langgraph.prebuilt import create_react_agent

from graphrag.agent.prompts import SYSTEM_PROMPT
from graphrag.agent.styles import style_instruction
from graphrag.agent.tools import ToolContext, build_tools
from graphrag.core.logging import get_logger
from graphrag.core.types import QueryResult, RetrievedChunk

log = get_logger(__name__)


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # Anthropic-style content blocks
        return "".join(b.get("text", "") for b in content if isinstance(b, dict))
    return str(content)


def build_checkpointer(redis_url: str | None, enabled: bool):
    """Durable agent memory in Redis (survives restarts / shared across replicas)
    when available; otherwise in-process memory; otherwise none."""
    if not enabled:
        return None
    if redis_url:
        try:
            # AsyncRedisSaver, not RedisSaver: /query streams over `astream`,
            # which needs `aget_tuple`. RedisSaver implements only the sync half
            # and inherits a base that raises NotImplementedError for the rest —
            # so streaming dies instantly while the non-streaming path works.
            from langgraph.checkpoint.redis import AsyncRedisSaver

            # Deliberately unset: `asetup()` is a coroutine and this is sync, and
            # driving one with asyncio.run() would bind the async Redis client to
            # a loop that closes on the way out. The API awaits asetup() during
            # its lifespan instead, on the loop that will actually serve requests
            # (see api/app.py). Until then the saver raises a clear RuntimeError
            # rather than misbehaving.
            saver = AsyncRedisSaver(redis_url=redis_url)
            log.info("agent_memory", backend="redis")
            return saver
        except Exception as exc:  # package missing or incompatible -> fall back
            log.warning("redis_checkpointer_unavailable", error=str(exc))
    from langgraph.checkpoint.memory import MemorySaver

    log.info("agent_memory", backend="in-process")
    return MemorySaver()


class AgentSession:
    """One question in flight. Holds the per-query source collector."""

    def __init__(self, agent, styled_question: str, config: dict, ctx: ToolContext) -> None:
        self._agent = agent
        self._input = {"messages": [HumanMessage(content=styled_question)]}
        self._config = config
        self._ctx = ctx

    @property
    def sources(self) -> list[RetrievedChunk]:
        return self._ctx.collected

    def run(self) -> QueryResult:
        result = self._agent.invoke(self._input, self._config)
        messages = result["messages"]
        answer = next(
            (_text(m.content) for m in reversed(messages)
             if isinstance(m, AIMessage) and _text(m.content).strip()),
            "",
        )
        tool_calls = [
            {"tool": tc["name"], "args": tc.get("args", {})}
            for m in messages if isinstance(m, AIMessage)
            for tc in (m.tool_calls or [])
        ]
        return QueryResult(answer=answer, sources=self.sources, tool_calls=tool_calls)

    async def astream_tokens(self) -> AsyncIterator[str]:
        async for msg, _meta in self._agent.astream(
            self._input, self._config, stream_mode="messages"
        ):
            if isinstance(msg, ToolMessage):
                continue
            if isinstance(msg, AIMessageChunk):
                text = _text(msg.content)
                if text:
                    yield text


class AgentRunner:
    def __init__(
        self,
        model: BaseChatModel,
        vector,
        hybrid,
        graph,
        checkpointer=None,
        *,
        top_k: int = 8,
        graph_hops: int = 2,
        default_style: str = "detailed",
    ) -> None:
        self._model = model
        self._vector = vector
        self._hybrid = hybrid
        self._graph = graph
        self._checkpointer = checkpointer
        self._top_k = top_k
        self._graph_hops = graph_hops
        self._default_style = default_style

    def _make_agent(self, ctx: ToolContext):
        tools = build_tools(ctx)
        try:
            return create_react_agent(
                self._model, tools, prompt=SYSTEM_PROMPT, checkpointer=self._checkpointer
            )
        except TypeError:  # older langgraph uses state_modifier
            return create_react_agent(
                self._model, tools, state_modifier=SYSTEM_PROMPT, checkpointer=self._checkpointer
            )

    def session(
        self, question: str, style: str | None = None, thread_id: str = "default"
    ) -> AgentSession:
        ctx = ToolContext(
            vector=self._vector,
            hybrid=self._hybrid,
            graph=self._graph,
            top_k=self._top_k,
            graph_hops=self._graph_hops,
        )
        agent = self._make_agent(ctx)
        instruction = style_instruction(style or self._default_style)
        styled = f"{instruction}\n\nQuestion: {question}"
        config = {"configurable": {"thread_id": thread_id}}
        return AgentSession(agent, styled, config, ctx)
