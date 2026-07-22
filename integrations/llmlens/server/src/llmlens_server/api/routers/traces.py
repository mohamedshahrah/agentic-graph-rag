"""Trace read endpoints for the dashboard (admin-gated when auth is on)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from llmlens_server.api.deps import get_ch, get_range, read_project
from llmlens_server.query import traces as trace_query

router = APIRouter(tags=["traces"])


@router.get("/api/traces")
def list_traces(
    user_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    rng=Depends(get_range),
    project_id: str = Depends(read_project),
    ch=Depends(get_ch),
) -> dict:
    since, until = rng
    rows = trace_query.list_traces(
        ch, project_id, since, until,
        user_id=user_id, status=status, limit=limit, offset=offset,
    )
    return {"traces": rows}


@router.get("/api/traces/{trace_id}")
def get_trace(
    trace_id: str,
    project_id: str = Depends(read_project),
    ch=Depends(get_ch),
) -> dict:
    return trace_query.get_trace(ch, project_id, trace_id)
