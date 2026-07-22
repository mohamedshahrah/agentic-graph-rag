"""Convert `Span` objects into ClickHouse rows and insert them."""

from __future__ import annotations

import json

from llmlens_server.core.types import Span
from llmlens_server.storage.clickhouse.client import insert_rows

SPAN_COLUMNS = [
    "project_id", "trace_id", "span_id", "parent_span_id", "name", "kind",
    "provider", "model", "start_time", "end_time", "duration_ms", "status",
    "status_message", "input_tokens", "output_tokens", "total_tokens", "cost_usd",
    "user_id", "session_id", "tags", "metadata",
]

CONTENT_COLUMNS = ["project_id", "trace_id", "span_id", "role", "content", "start_time"]


def _span_row(span: Span) -> tuple:
    end = span.end_time or span.start_time
    return (
        span.project_id, span.trace_id, span.span_id, span.parent_span_id, span.name,
        span.kind.value, span.provider, span.model, span.start_time, end, span.duration_ms,
        span.status.value, span.status_message, span.input_tokens, span.output_tokens,
        span.total_tokens, span.cost_usd, span.user_id, span.session_id, span.tags,
        json.dumps(span.metadata, default=str),
    )


def write_spans(client, spans: list[Span], record_content: bool = True) -> None:
    if not spans:
        return
    insert_rows(client, "spans", SPAN_COLUMNS, [_span_row(s) for s in spans])

    if record_content:
        content_rows = [
            (s.project_id, s.trace_id, s.span_id, item.role, item.content, s.start_time)
            for s in spans
            for item in s.content
        ]
        insert_rows(client, "span_content", CONTENT_COLUMNS, content_rows)
