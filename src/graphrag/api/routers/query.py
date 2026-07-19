"""Ask questions. `/query` runs the agent (streaming by default); `/compare`
is a convenience that phrases a side-by-side comparison. Both are scoped to the
current user and metered against their limits."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sse_starlette.sse import EventSourceResponse

from graphrag.api.deps import AuthUser, get_container, get_db, get_query_service
from graphrag.api.schemas import (
    CompareRequest,
    QueryRequest,
    QueryResponse,
    Source,
    ToolCall,
)
from graphrag.api.streaming import sse_answer
from graphrag.container import Container
from graphrag.db.engine import session_scope
from graphrag.db.models import Message, Thread
from graphrag.limits import enforce_message_limits
from graphrag.llm.registry import resolve_model
from graphrag.pipelines import QueryService

router = APIRouter(tags=["query"])


def _shape(result) -> QueryResponse:
    return QueryResponse(
        answer=result.answer,
        sources=[Source.from_chunk(c) for c in result.sources],
        tool_calls=[ToolCall(**tc) for tc in result.tool_calls],
    )


def _chat_model(container: Container, requested: str | None):
    """Registry-validated model override, or None for the default. A raw
    request string never reaches a provider client."""
    if not requested:
        return None
    m = resolve_model(requested, container.settings)
    return container.chat_model(m.provider, m.model)


async def _owned_thread(db, user: AuthUser, thread_id: str) -> str | None:
    """Confirm the caller owns this conversation, and return its id.

    Returns None when there is nothing to check against (no database, or a
    dev-mode identity), which leaves the old free-form thread ids working.
    """
    if db is None or not thread_id or thread_id == "default":
        return None
    try:
        owner = uuid.UUID(str(user.user_id))
        tid = uuid.UUID(thread_id)
    except (ValueError, AttributeError, TypeError):
        return None
    async with session_scope(db) as s:
        found = (
            await s.execute(
                select(Thread.id).where(
                    Thread.id == tid, Thread.user_id == owner, Thread.deleted_at.is_(None)
                )
            )
        ).scalar_one_or_none()
    if found is None:
        raise HTTPException(status_code=404, detail="No such conversation.")
    return str(found)


async def _save_turn(
    db, thread_id: str | None, question: str, answer: str, sources, model: str
) -> None:
    """Persist one exchange. Never raises: the answer already reached the user,
    and losing a transcript row must not turn a served request into an error."""
    if db is None or not thread_id:
        return
    from graphrag.core.logging import get_logger

    try:
        async with session_scope(db) as s:
            s.add(Message(thread_id=uuid.UUID(thread_id), role="user", content=question))
            s.add(
                Message(
                    thread_id=uuid.UUID(thread_id),
                    role="assistant",
                    content=answer,
                    sources=[Source.from_chunk(c).model_dump() for c in sources],
                    model=model or None,
                )
            )
            thread = (
                await s.execute(select(Thread).where(Thread.id == uuid.UUID(thread_id)))
            ).scalar_one_or_none()
            if thread is not None and thread.title == "New chat":
                # Name the conversation after its opening question, so the
                # sidebar is scannable without the user renaming anything.
                thread.title = question.strip()[:60] or "New chat"
    except Exception as exc:
        get_logger(__name__).warning("transcript_save_failed", error=str(exc))


@router.post("/query", response_model=QueryResponse | None)
async def query(
    req: QueryRequest,
    request: Request,
    service: QueryService = Depends(get_query_service),
    container: Container = Depends(get_container),
    user: AuthUser = Depends(enforce_message_limits),
    db=Depends(get_db),
):
    thread_id = await _owned_thread(db, user, req.thread_id)
    stream = req.stream if req.stream is not None else container.settings.api.stream
    chosen = resolve_model(req.model, container.settings) if req.model else None
    model = container.chat_model(chosen.provider, chosen.model) if chosen else None
    model_name = chosen.model if chosen else container.settings.llm.model

    if stream:
        return EventSourceResponse(
            sse_answer(
                service, req.question, req.style, req.thread_id, user.tenant_id,
                redis_client=container.redis, model=model,
                recorder=getattr(request.app.state, "usage", None),
                account_id=user.user_id,
                on_complete=lambda answer, sources: _save_turn(
                    db, thread_id, req.question, answer, sources, model_name
                ),
            )
        )
    # Async, not sync-in-threadpool: the API's checkpointer is the async saver,
    # which refuses sync `.invoke()`.
    result = await service.aanswer(
        req.question, style=req.style, thread_id=req.thread_id,
        user_id=user.tenant_id, model=model,
    )
    await _save_turn(db, thread_id, req.question, result.answer, result.sources, model_name)
    return _shape(result)


@router.post("/compare", response_model=QueryResponse)
async def compare(
    req: CompareRequest,
    service: QueryService = Depends(get_query_service),
    container: Container = Depends(get_container),
    user: AuthUser = Depends(enforce_message_limits),
):
    subjects = ", ".join(req.subjects)
    aspects = ("along these aspects: " + ", ".join(req.aspects)) if req.aspects else ""
    question = f"Compare {subjects} {aspects}. Present the comparison as a table."
    result = await service.aanswer(
        question, style=req.style, thread_id=req.thread_id, user_id=user.tenant_id,
        model=_chat_model(container, req.model),
    )
    return _shape(result)
