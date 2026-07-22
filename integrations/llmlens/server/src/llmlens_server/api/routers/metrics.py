"""Metric read endpoints — overview, time series, cost breakdowns, top errors."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from llmlens_server.api.deps import get_ch, get_range, read_project
from llmlens_server.query import metrics as m

router = APIRouter(tags=["metrics"], prefix="/api/metrics")


@router.get("/overview")
def overview(rng=Depends(get_range), project_id: str = Depends(read_project), ch=Depends(get_ch)):
    since, until = rng
    return m.overview(ch, project_id, since, until)


@router.get("/timeseries")
def timeseries(rng=Depends(get_range), project_id: str = Depends(read_project), ch=Depends(get_ch)):
    since, until = rng
    return {"points": m.timeseries(ch, project_id, since, until)}


@router.get("/cost/users")
def cost_users(rng=Depends(get_range), project_id: str = Depends(read_project), ch=Depends(get_ch)):
    since, until = rng
    return {"users": m.cost_by_user(ch, project_id, since, until)}


@router.get("/cost/models")
def cost_models(
    rng=Depends(get_range), project_id: str = Depends(read_project), ch=Depends(get_ch)
):
    since, until = rng
    return {"models": m.cost_by_model(ch, project_id, since, until)}


@router.get("/errors")
def errors(rng=Depends(get_range), project_id: str = Depends(read_project), ch=Depends(get_ch)):
    since, until = rng
    return {"errors": m.top_errors(ch, project_id, since, until)}
