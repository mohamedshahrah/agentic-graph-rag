"""Trace read models for the dashboard: a filtered list, and a single trace
assembled into a span tree (the waterfall) with attached prompt/response content."""

from __future__ import annotations

import json
from datetime import datetime

from llmlens_server.storage.clickhouse import queries


def list_traces(ch_client, project_id: str, since: datetime, until: datetime, **kw) -> list[dict]:
    rows = queries.list_traces(ch_client, project_id, since, until, **kw)
    for r in rows:
        r["has_error"] = bool(r.get("has_error"))
    return rows


def get_trace(ch_client, project_id: str, trace_id: str) -> dict:
    spans = queries.get_trace_spans(ch_client, project_id, trace_id)
    content = queries.get_trace_content(ch_client, project_id, trace_id)

    by_span: dict[str, list[dict]] = {}
    for c in content:
        by_span.setdefault(c["span_id"], []).append({"role": c["role"], "content": c["content"]})

    nodes: dict[str, dict] = {}
    for s in spans:
        s["metadata"] = _parse_json(s.get("metadata"))
        s["content"] = by_span.get(s["span_id"], [])
        s["children"] = []
        nodes[s["span_id"]] = s

    roots: list[dict] = []
    for s in spans:
        parent = nodes.get(s["parent_span_id"])
        if parent and parent is not s:
            parent["children"].append(s)
        else:
            roots.append(s)

    span0 = spans[0] if spans else {}
    return {
        "trace_id": trace_id,
        "spans": roots,
        "span_count": len(spans),
        "user_id": span0.get("user_id", ""),
    }


def _parse_json(value) -> dict:
    if not value:
        return {}
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return {}
