"""HTTP request/response models. Trace/metric reads return plain JSON dicts
(the shapes come straight from the query layer), so only inputs and small
outputs are modeled here."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class IngestRequest(BaseModel):
    events: list[dict[str, Any]] = Field(default_factory=list)


class IngestResponse(BaseModel):
    accepted: int


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)


class ProjectCreated(BaseModel):
    id: str
    name: str
    secret_key: str  # shown once


class ChannelCreate(BaseModel):
    project_id: str = "default"
    kind: str = Field(..., description="webhook | slack | log")
    target: str = ""


class AlertRuleCreate(BaseModel):
    project_id: str = "default"
    name: str
    type: str = Field(..., description="error_rate | cost_spike | latency_p95 | volume")
    threshold: float
    window_seconds: int = 300
    cooldown_seconds: int = 900
    channel_id: int | None = None


class RuleUpdate(BaseModel):
    enabled: bool


class IdResponse(BaseModel):
    id: int


class Health(BaseModel):
    status: str
    version: str


class Ready(BaseModel):
    ready: bool
    clickhouse: bool
    postgres: bool
    redis: bool
