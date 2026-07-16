"""Query service: run a user's agent and shape its output for the API. Every
call is scoped to one user's namespace, and conversation memory is keyed per
user so threads never bleed across accounts."""

from __future__ import annotations

from collections.abc import AsyncIterator

from graphrag.agent import AgentSession
from graphrag.container import Container
from graphrag.core.types import QueryResult, RetrievedChunk


class QueryService:
    def __init__(self, container: Container) -> None:
        self._c = container

    def _session(
        self, question: str, style: str | None, thread_id: str, user_id: str | None
    ) -> AgentSession:
        tenant = self._c.tenant(user_id)
        # Namespace the memory thread with the user so conversations stay private.
        return tenant.agent.session(
            question, style=style, thread_id=f"{tenant.user_id}:{thread_id}"
        )

    def answer(
        self,
        question: str,
        style: str | None = None,
        thread_id: str = "default",
        user_id: str | None = None,
    ) -> QueryResult:
        return self._session(question, style, thread_id, user_id).run()

    async def stream(
        self,
        question: str,
        style: str | None = None,
        thread_id: str = "default",
        user_id: str | None = None,
    ) -> AsyncIterator[tuple[str, list[RetrievedChunk]]]:
        session = self._session(question, style, thread_id, user_id)
        async for token in session.astream_tokens():
            yield token, session.sources

    def search(self, query: str, k: int = 8, user_id: str | None = None) -> list[RetrievedChunk]:
        return self._c.tenant(user_id).hybrid_retriever.retrieve(query, k)
