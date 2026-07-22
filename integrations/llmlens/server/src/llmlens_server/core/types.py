"""Canonical internal telemetry types. Both the native ingest path and the OTLP
receiver normalize incoming data into `Span` objects, which the ClickHouse writer
then persists. One row per span (a.k.a. observation)."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


class SpanKind(enum.StrEnum):
    TRACE = "trace"            # the root of a trace
    GENERATION = "generation"  # an LLM call
    SPAN = "span"              # a generic step (chain, retrieval)
    TOOL = "tool"              # a tool / function call
    EVENT = "event"            # a point-in-time event


class SpanStatus(enum.StrEnum):
    OK = "ok"
    ERROR = "error"


@dataclass(slots=True)
class ContentItem:
    """A prompt or completion message, stored separately (opt-in, redactable)."""

    role: str          # system | user | assistant | tool | input | output
    content: str


@dataclass(slots=True)
class Span:
    project_id: str
    trace_id: str
    span_id: str
    name: str
    kind: SpanKind
    start_time: datetime
    end_time: datetime | None = None
    parent_span_id: str = ""
    provider: str = ""
    model: str = ""
    status: SpanStatus = SpanStatus.OK
    status_message: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    user_id: str = ""
    session_id: str = ""
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    content: list[ContentItem] = field(default_factory=list)

    @property
    def duration_ms(self) -> float:
        if self.end_time is None:
            return 0.0
        return (self.end_time - self.start_time).total_seconds() * 1000.0
