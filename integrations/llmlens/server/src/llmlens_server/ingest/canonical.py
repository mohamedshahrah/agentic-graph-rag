"""The canonical event dict is what flows through the Redis queue — a JSON-safe
form of a Span. Both the native SDK payload and the OTLP receiver produce these;
the worker turns them back into `Span` objects (adding cost)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from llmlens_server.core.errors import IngestError
from llmlens_server.core.types import ContentItem, Span, SpanKind, SpanStatus

_VALID_KINDS = {k.value for k in SpanKind}


def _parse_time(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        # Epoch tiers (today ≈ 1.7e9 s / 1.7e12 ms / 1.7e15 µs / 1.7e18 ns).
        v = float(value)
        if v > 1e17:
            v /= 1e9  # nanoseconds
        elif v > 1e14:
            v /= 1e6  # microseconds
        elif v > 1e11:
            v /= 1e3  # milliseconds
        try:
            return datetime.fromtimestamp(v, tz=UTC)
        except (OverflowError, OSError, ValueError) as exc:
            raise IngestError(f"Unparseable timestamp: {value!r}") from exc
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise IngestError(f"Unparseable timestamp: {value!r}") from exc
    raise IngestError(f"Unparseable timestamp: {value!r}")


def event_to_span(event: dict) -> Span:
    kind = event.get("kind", "span")
    if kind not in _VALID_KINDS:
        kind = "span"
    status = "error" if event.get("status") == "error" else "ok"
    content = [
        ContentItem(role=c.get("role", "input"), content=str(c.get("content", "")))
        for c in event.get("content", []) or []
        if c.get("content")
    ]
    in_tok = int(event.get("input_tokens") or 0)
    out_tok = int(event.get("output_tokens") or 0)
    total = int(event.get("total_tokens") or (in_tok + out_tok))
    return Span(
        project_id=event["project_id"],
        trace_id=event["trace_id"],
        span_id=event["span_id"],
        parent_span_id=event.get("parent_span_id", "") or "",
        name=event.get("name", "") or "",
        kind=SpanKind(kind),
        start_time=_parse_time(event["start_time"]),
        end_time=_parse_time(event["end_time"]) if event.get("end_time") else None,
        provider=event.get("provider", "") or "",
        model=event.get("model", "") or "",
        status=SpanStatus(status),
        status_message=event.get("status_message", "") or "",
        input_tokens=in_tok,
        output_tokens=out_tok,
        total_tokens=total,
        cost_usd=float(event.get("cost_usd") or 0.0),
        user_id=event.get("user_id", "") or "",
        session_id=event.get("session_id", "") or "",
        tags=list(event.get("tags") or []),
        metadata=dict(event.get("metadata") or {}),
        content=content,
    )
