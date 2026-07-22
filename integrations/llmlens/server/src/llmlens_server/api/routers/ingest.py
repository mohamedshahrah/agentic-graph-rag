"""Native ingest endpoint. Authenticates the project, normalizes events, and
enqueues them for the worker. Returns immediately (non-blocking for the app)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from llmlens_server.api.deps import get_redis_client, get_settings, ingest_project
from llmlens_server.api.schemas import IngestRequest, IngestResponse
from llmlens_server.core.errors import IngestError
from llmlens_server.ingest import enqueue, parse_native

router = APIRouter(tags=["ingest"])


@router.post("/api/v1/ingest", response_model=IngestResponse)
def ingest(
    payload: IngestRequest,
    request: Request,
    project_id: str = Depends(ingest_project),
    redis=Depends(get_redis_client),
    settings=Depends(get_settings),
) -> IngestResponse:
    try:
        events = parse_native(payload.events, project_id)
    except IngestError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    accepted = enqueue(redis, settings.ingest.queue_stream, events)
    return IngestResponse(accepted=accepted)
