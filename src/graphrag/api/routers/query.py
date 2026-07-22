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
    SafetyInfo,
    Source,
    ToolCall,
)
from graphrag.api.streaming import sse_answer, sse_message, sse_refusal
from graphrag.agent.prompts import CLOSED_DOMAIN_REFUSAL
from graphrag.container import Container
from graphrag.db.engine import session_scope
from graphrag.db.models import Message, Thread
from graphrag.limits import enforce_message_limits
from graphrag.llm.registry import resolve_model
from graphrag.pipelines import QueryService

router = APIRouter(tags=["query"])

# Bound what the output guard sees: the groundedness check only needs the
# retrieved evidence, and forwarding the whole corpus would be slow and could
# trip the guard's own input-size caps.
_MAX_GUARD_DOCS = 8
_MAX_DOC_CHARS = 4000

_REFUSAL = "I can't help with that request."


def _context_docs(sources) -> list[dict[str, str]]:
    """Retrieved chunks in the guard's `context_docs` shape (enables the
    output-direction groundedness / hallucination check)."""
    return [
        {"id": c.chunk_id, "text": c.text[:_MAX_DOC_CHARS], "source": c.source}
        for c in sources[:_MAX_GUARD_DOCS]
    ]


def _safety_info(verdict, stage: str) -> SafetyInfo | None:
    """Surface a block/flag/redaction to the client; None when the guard allowed."""
    if verdict.blocked:
        action = "block"
    elif verdict.modified:
        action = "redacted"
    elif verdict.flagged:
        action = "flag"
    else:
        return None
    return SafetyInfo(action=action, stage=stage, reasons=list(verdict.reasons))


def _response(answer: str, sources, tool_calls, safety: SafetyInfo | None = None) -> QueryResponse:
    return QueryResponse(
        answer=answer,
        sources=[Source.from_chunk(c) for c in sources],
        tool_calls=[ToolCall(**tc) for tc in tool_calls],
        safety=safety,
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

    guard = container.guardrails

    # Guardrails input check — before the model runs. A block short-circuits the
    # whole request: no agent, no retrieval, no tokens spent. No-op when
    # safety.enabled is false (guard.check_input returns an `allow`).
    if guard.enabled:
        v_in = await guard.check_input(req.question)
        if v_in.blocked:
            refusal = v_in.refusal_message or _REFUSAL
            await _save_turn(db, thread_id, req.question, refusal, [], model_name)
            if stream:
                return EventSourceResponse(sse_refusal(refusal))
            return _response(refusal, [], [], _safety_info(v_in, "input"))

    # Closed-domain gate: only answer when the knowledge base actually covers the
    # question. One probe retrieval; if nothing clears retrieval.min_relevance, we
    # refuse here — an off-topic question gets an honest "not in the KB" instead of
    # a general-knowledge answer. min_relevance = 0 disables the gate.
    min_rel = container.settings.retrieval.min_relevance
    if min_rel > 0:
        probe = service.search(req.question, user_id=user.tenant_id)
        if not probe or probe[0].score < min_rel:
            await _save_turn(db, thread_id, req.question, CLOSED_DOMAIN_REFUSAL, [], model_name)
            if stream:
                return EventSourceResponse(sse_message(CLOSED_DOMAIN_REFUSAL))
            return _response(CLOSED_DOMAIN_REFUSAL, [], [])

    if stream:
        async def _out_guard(answer, sources):
            return await guard.check_output(
                req.question, answer, docs=_context_docs(sources)
            )

        return EventSourceResponse(
            sse_answer(
                service, req.question, req.style, req.thread_id, user.tenant_id,
                redis_client=container.redis, model=model,
                recorder=getattr(request.app.state, "usage", None),
                account_id=user.user_id,
                output_guard=_out_guard if guard.enabled else None,
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
    answer, sources, tool_calls = result.answer, result.sources, result.tool_calls

    # Guardrails output check — the non-streaming path can enforce fully: block
    # (withhold the answer) or redact (swap in the sanitized, PII-clean text).
    # The verdict rides back on the response so the UI can show why.
    safety = None
    if guard.enabled:
        v_out = await guard.check_output(
            req.question, answer, docs=_context_docs(sources)
        )
        if v_out.blocked:
            answer, sources, tool_calls = (v_out.refusal_message or _REFUSAL), [], []
        elif v_out.modified and v_out.sanitized_output is not None:
            answer = v_out.sanitized_output
        safety = _safety_info(v_out, "output")

    await _save_turn(db, thread_id, req.question, answer, sources, model_name)
    return _response(answer, sources, tool_calls, safety)


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

    guard = container.guardrails
    if guard.enabled:
        # Screen the composed question: subjects AND aspects are user-supplied,
        # and either one can carry an injection.
        v_in = await guard.check_input(question)
        if v_in.blocked:
            return _response(
                v_in.refusal_message or _REFUSAL, [], [], _safety_info(v_in, "input")
            )

    min_rel = container.settings.retrieval.min_relevance
    if min_rel > 0:
        probe = service.search(question, user_id=user.tenant_id)
        if not probe or probe[0].score < min_rel:
            return _response(CLOSED_DOMAIN_REFUSAL, [], [])

    result = await service.aanswer(
        question, style=req.style, thread_id=req.thread_id, user_id=user.tenant_id,
        model=_chat_model(container, req.model),
    )
    answer, sources, tool_calls = result.answer, result.sources, result.tool_calls

    safety = None
    if guard.enabled:
        v_out = await guard.check_output(question, answer, docs=_context_docs(sources))
        if v_out.blocked:
            answer, sources, tool_calls = (v_out.refusal_message or _REFUSAL), [], []
        elif v_out.modified and v_out.sanitized_output is not None:
            answer = v_out.sanitized_output
        safety = _safety_info(v_out, "output")

    return _response(answer, sources, tool_calls, safety)
