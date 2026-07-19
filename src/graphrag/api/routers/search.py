"""Raw retrieval with no LLM — inspect exactly what the hybrid retriever returns
for the current user."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from graphrag.api.deps import AuthUser, get_current_user, get_query_service
from graphrag.api.schemas import SearchRequest, SearchResponse, Source
from graphrag.pipelines import QueryService

router = APIRouter(tags=["search"])


@router.post("/search", response_model=SearchResponse)
async def search(
    req: SearchRequest,
    service: QueryService = Depends(get_query_service),
    user: AuthUser = Depends(get_current_user),
):
    chunks = service.search(req.query, req.k, user_id=user.tenant_id)
    return SearchResponse(results=[Source.from_chunk(c) for c in chunks])
