"""Parse OTLP/HTTP JSON trace payloads into canonical events, reading the
OpenTelemetry GenAI (`gen_ai.*`) semantic conventions. This is what lets any
standard OpenTelemetry-instrumented app send data to llmlens."""

from __future__ import annotations

from typing import Any

from llmlens_server.core import semconv as sc


def _any_value(v: dict) -> Any:
    if "stringValue" in v:
        return v["stringValue"]
    if "intValue" in v:
        return int(v["intValue"])
    if "doubleValue" in v:
        return float(v["doubleValue"])
    if "boolValue" in v:
        return bool(v["boolValue"])
    if "arrayValue" in v:
        return [_any_value(x) for x in v["arrayValue"].get("values", [])]
    return None


def _attrs(attr_list: list[dict]) -> dict[str, Any]:
    return {a["key"]: _any_value(a.get("value", {})) for a in attr_list or []}


def _kind(attrs: dict) -> str:
    if sc.GEN_AI_REQUEST_MODEL in attrs or sc.GEN_AI_SYSTEM in attrs:
        return "generation"
    op = attrs.get(sc.GEN_AI_OPERATION, "")
    if "tool" in str(op).lower():
        return "tool"
    return "span"


def parse_otlp(payload: dict, project_id: str) -> list[dict]:
    events: list[dict] = []
    for rspans in payload.get("resourceSpans", []):
        for sspans in rspans.get("scopeSpans", []):
            for span in sspans.get("spans", []):
                events.append(_span_to_event(span, project_id))
    return events


def _span_to_event(span: dict, project_id: str) -> dict:
    attrs = _attrs(span.get("attributes", []))
    reserved = {
        sc.GEN_AI_SYSTEM, sc.GEN_AI_OPERATION, sc.GEN_AI_REQUEST_MODEL,
        sc.GEN_AI_RESPONSE_MODEL, sc.GEN_AI_RESPONSE_FINISH,
        sc.GEN_AI_USAGE_INPUT_TOKENS, sc.GEN_AI_USAGE_OUTPUT_TOKENS,
        sc.GEN_AI_INPUT_MESSAGES, sc.GEN_AI_OUTPUT_MESSAGES,
        sc.LLMLENS_USER_ID, sc.LLMLENS_SESSION_ID, sc.LLMLENS_TAGS,
    }
    status_obj = span.get("status", {})
    status = "error" if status_obj.get("code") == 2 else "ok"

    content = []
    if attrs.get(sc.GEN_AI_INPUT_MESSAGES):
        content.append({"role": "input", "content": str(attrs[sc.GEN_AI_INPUT_MESSAGES])})
    if attrs.get(sc.GEN_AI_OUTPUT_MESSAGES):
        content.append({"role": "output", "content": str(attrs[sc.GEN_AI_OUTPUT_MESSAGES])})

    return {
        "project_id": project_id,
        "trace_id": span.get("traceId", ""),
        "span_id": span.get("spanId", ""),
        "parent_span_id": span.get("parentSpanId", ""),
        "name": span.get("name", ""),
        "kind": _kind(attrs),
        "start_time": int(span.get("startTimeUnixNano", 0)),
        "end_time": int(span["endTimeUnixNano"]) if span.get("endTimeUnixNano") else None,
        "provider": attrs.get(sc.GEN_AI_SYSTEM, ""),
        "model": attrs.get(sc.GEN_AI_REQUEST_MODEL) or attrs.get(sc.GEN_AI_RESPONSE_MODEL, ""),
        "status": status,
        "status_message": status_obj.get("message", ""),
        "input_tokens": attrs.get(sc.GEN_AI_USAGE_INPUT_TOKENS, 0),
        "output_tokens": attrs.get(sc.GEN_AI_USAGE_OUTPUT_TOKENS, 0),
        "user_id": attrs.get(sc.LLMLENS_USER_ID, ""),
        "session_id": attrs.get(sc.LLMLENS_SESSION_ID, ""),
        "tags": attrs.get(sc.LLMLENS_TAGS) or [],
        "metadata": {k: v for k, v in attrs.items() if k not in reserved},
        "content": content,
    }
