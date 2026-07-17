"""Ask questions. `/query` runs the agent (streaming by default); `/compare`
is a convenience that phrases a side-by-side comparison. Both are scoped to the
current user (resolved from the API key when auth is on, else the X-User-Id
header)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sse_starlette.sse import EventSourceResponse

from graphrag.api.deps import get_container, get_current_user, get_query_service
from graphrag.api.schemas import (
    CompareRequest,
    QueryRequest,
    QueryResponse,
    Source,
    ToolCall,
)
from graphrag.api.streaming import sse_answer
from graphrag.container import Container
from graphrag.pipelines import QueryService

router = APIRouter(tags=["query"])


def _shape(result) -> QueryResponse:
    return QueryResponse(
        answer=result.answer,
        sources=[Source.from_chunk(c) for c in result.sources],
        tool_calls=[ToolCall(**tc) for tc in result.tool_calls],
    )


@router.post("/query", response_model=QueryResponse | None)
async def query(
    req: QueryRequest,
    service: QueryService = Depends(get_query_service),
    container: Container = Depends(get_container),
    user: str | None = Depends(get_current_user),
):
    stream = req.stream if req.stream is not None else container.settings.api.stream
    if stream:
        return EventSourceResponse(
            sse_answer(
                service, req.question, req.style, req.thread_id, user,
                redis_client=container.redis,
            )
        )
    # Async, not sync-in-threadpool: the API's checkpointer is the async saver,
    # which refuses sync `.invoke()`.
    result = await service.aanswer(
        req.question, style=req.style, thread_id=req.thread_id, user_id=user
    )
    return _shape(result)


@router.post("/compare", response_model=QueryResponse)
async def compare(
    req: CompareRequest,
    service: QueryService = Depends(get_query_service),
    user: str | None = Depends(get_current_user),
):
    subjects = ", ".join(req.subjects)
    aspects = ("along these aspects: " + ", ".join(req.aspects)) if req.aspects else ""
    question = f"Compare {subjects} {aspects}. Present the comparison as a table."
    result = await service.aanswer(
        question, style=req.style, thread_id=req.thread_id, user_id=user
    )
    return _shape(result)
