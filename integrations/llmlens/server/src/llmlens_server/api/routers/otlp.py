"""OTLP/HTTP trace receiver — accepts standard OpenTelemetry span exports (JSON)
and maps gen_ai.* attributes into the same pipeline as native events."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from llmlens_server.api.deps import get_redis_client, get_settings, ingest_project
from llmlens_server.ingest import enqueue, parse_otlp

router = APIRouter(tags=["otlp"])


@router.post("/v1/traces")
async def otlp_traces(
    request: Request,
    project_id: str = Depends(ingest_project),
    redis=Depends(get_redis_client),
    settings=Depends(get_settings),
) -> dict:
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Expected a JSON object")
    events = parse_otlp(payload, project_id)
    # enqueue uses the sync Redis client — keep it off the event loop.
    accepted = await run_in_threadpool(enqueue, redis, settings.ingest.queue_stream, events)
    # OTLP expects an empty-ish success body.
    return {"partialSuccess": {}, "accepted": accepted}
