"""Alert channels, rules, and event history."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from llmlens_server.alerting import validate_rule_type
from llmlens_server.api.deps import get_pg, read_project, require_admin
from llmlens_server.api.schemas import AlertRuleCreate, ChannelCreate, IdResponse, RuleUpdate
from llmlens_server.storage.postgres import repos

router = APIRouter(tags=["alerts"], prefix="/api/alerts")


@router.post("/channels", response_model=IdResponse)
def create_channel(
    payload: ChannelCreate, _: None = Depends(require_admin), pg=Depends(get_pg)
) -> IdResponse:
    cid = repos.create_channel(pg, payload.project_id, payload.kind, payload.target)
    return IdResponse(id=cid)


@router.get("/channels")
def list_channels(project_id: str = Depends(read_project), pg=Depends(get_pg)) -> dict:
    return {"channels": repos.list_channels(pg, project_id)}


@router.delete("/channels/{channel_id}")
def delete_channel(
    channel_id: int, _: None = Depends(require_admin), pg=Depends(get_pg)
) -> dict:
    if not repos.delete_channel(pg, channel_id):
        raise HTTPException(status_code=404, detail="Channel not found")
    return {"deleted": channel_id}


@router.post("/rules", response_model=IdResponse)
def create_rule(
    payload: AlertRuleCreate, _: None = Depends(require_admin), pg=Depends(get_pg)
) -> IdResponse:
    try:
        validate_rule_type(payload.type)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    rid = repos.create_rule(pg, payload.model_dump())
    return IdResponse(id=rid)


@router.get("/rules")
def list_rules(project_id: str = Depends(read_project), pg=Depends(get_pg)) -> dict:
    return {"rules": repos.list_rules(pg, project_id=project_id)}


@router.patch("/rules/{rule_id}")
def update_rule(
    rule_id: int, payload: RuleUpdate, _: None = Depends(require_admin), pg=Depends(get_pg)
) -> dict:
    if not repos.set_rule_enabled(pg, rule_id, payload.enabled):
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"id": rule_id, "enabled": payload.enabled}


@router.delete("/rules/{rule_id}")
def delete_rule(
    rule_id: int, _: None = Depends(require_admin), pg=Depends(get_pg)
) -> dict:
    """Removes the rule and its fired-event history (FK cascade)."""
    if not repos.delete_rule(pg, rule_id):
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"deleted": rule_id}


@router.get("/events")
def list_events(project_id: str = Depends(read_project), pg=Depends(get_pg)) -> dict:
    return {"events": repos.list_alert_events(pg, project_id)}
