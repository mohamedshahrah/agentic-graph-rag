"""Read queries for the dashboard. Metric queries hit the pre-aggregated
`metrics_by_minute` materialized view; trace queries hit `spans` directly."""

from __future__ import annotations

import math
from datetime import datetime

from llmlens_server.storage.clickhouse.client import query


def _finite(value) -> float:
    """Quantile aggregates over an empty window return NaN, which the JSON
    encoder (allow_nan=False) turns into a 500. Coerce to 0.0."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 0.0
    return f if math.isfinite(f) else 0.0


def list_traces(
    client, project_id: str, since: datetime, until: datetime,
    user_id: str | None = None, status: str | None = None,
    limit: int = 50, offset: int = 0,
) -> list[dict]:
    where = ["project_id = {project_id:String}", "start_time >= {since:DateTime64(3)}",
             "start_time <= {until:DateTime64(3)}"]
    params: dict = {"project_id": project_id, "since": since, "until": until,
                    "limit": limit, "offset": offset}
    if user_id:
        where.append("user_id = {user_id:String}")
        params["user_id"] = user_id
    having = ""
    if status == "error":
        having = "HAVING has_error = 1"
    elif status == "ok":
        having = "HAVING has_error = 0"

    # NB: the aggregate alias must NOT be named `start_time` — ClickHouse
    # substitutes SELECT aliases into WHERE, turning the time filter into an
    # illegal `min(start_time) >= ...` aggregation.
    sql = f"""
        SELECT trace_id,
               argMin(name, start_time)                                   AS name,
               min(start_time)                                            AS first_start,
               (toUnixTimestamp64Milli(max(end_time))
                - toUnixTimestamp64Milli(min(start_time)))                AS duration_ms,
               sum(cost_usd)                                              AS cost_usd,
               sum(total_tokens)                                          AS tokens,
               count()                                                    AS spans,
               max(status = 'error')                                      AS has_error,
               any(user_id)                                               AS user_id
        FROM spans WHERE {' AND '.join(where)}
        GROUP BY trace_id {having}
        ORDER BY first_start DESC
        LIMIT {{limit:UInt32}} OFFSET {{offset:UInt32}}
    """
    rows = query(client, sql, params)
    for r in rows:
        r["start_time"] = r.pop("first_start")  # keep the API shape stable
    return rows


def get_trace_spans(client, project_id: str, trace_id: str) -> list[dict]:
    sql = """
        SELECT span_id, parent_span_id, name, kind, provider, model,
               toUnixTimestamp64Milli(start_time) AS start_ms,
               toUnixTimestamp64Milli(end_time)   AS end_ms,
               duration_ms, status, status_message,
               input_tokens, output_tokens, total_tokens, cost_usd,
               user_id, session_id, tags, metadata
        FROM spans
        WHERE project_id = {project_id:String} AND trace_id = {trace_id:String}
        ORDER BY start_time ASC
    """
    return query(client, sql, {"project_id": project_id, "trace_id": trace_id})


def get_trace_content(client, project_id: str, trace_id: str) -> list[dict]:
    sql = """
        SELECT span_id, role, content
        FROM span_content
        WHERE project_id = {project_id:String} AND trace_id = {trace_id:String}
    """
    return query(client, sql, {"project_id": project_id, "trace_id": trace_id})


def metrics_overview(client, project_id: str, since: datetime, until: datetime) -> dict:
    sql = """
        SELECT sum(count)                              AS requests,
               sum(errors)                             AS errors,
               sum(cost_usd)                           AS cost_usd,
               sum(input_tokens + output_tokens)       AS tokens,
               quantilesTDigestMerge(0.5, 0.95, 0.99)(latency_state) AS lat
        FROM metrics_by_minute
        WHERE project_id = {project_id:String}
          AND minute >= {since:DateTime} AND minute <= {until:DateTime}
    """
    rows = query(client, sql, {"project_id": project_id, "since": since, "until": until})
    row = rows[0] if rows else {}
    lat = row.get("lat") or [0, 0, 0]
    requests = int(row.get("requests") or 0)
    errors = int(row.get("errors") or 0)
    return {
        "requests": requests,
        "errors": errors,
        "error_rate": (errors / requests) if requests else 0.0,
        "cost_usd": _finite(row.get("cost_usd")),
        "tokens": int(row.get("tokens") or 0),
        "latency_p50": _finite(lat[0]), "latency_p95": _finite(lat[1]),
        "latency_p99": _finite(lat[2]),
    }


def metrics_timeseries(client, project_id: str, since: datetime, until: datetime) -> list[dict]:
    sql = """
        SELECT minute,
               sum(count)     AS requests,
               sum(errors)    AS errors,
               sum(cost_usd)  AS cost_usd,
               quantilesTDigestMerge(0.5, 0.95, 0.99)(latency_state) AS lat
        FROM metrics_by_minute
        WHERE project_id = {project_id:String}
          AND minute >= {since:DateTime} AND minute <= {until:DateTime}
        GROUP BY minute ORDER BY minute
    """
    out = []
    for r in query(client, sql, {"project_id": project_id, "since": since, "until": until}):
        lat = r.get("lat") or [0, 0, 0]
        out.append({
            "minute": r["minute"], "requests": int(r["requests"]), "errors": int(r["errors"]),
            "cost_usd": _finite(r["cost_usd"]),
            "latency_p50": _finite(lat[0]), "latency_p95": _finite(lat[1]),
            "latency_p99": _finite(lat[2]),
        })
    return out


def cost_by_user(client, project_id: str, since: datetime, until: datetime, limit: int = 20):
    sql = """
        SELECT if(user_id = '', '(unknown)', user_id) AS user_id,
               sum(cost_usd)     AS cost_usd,
               count()           AS requests,
               sum(total_tokens) AS tokens
        FROM spans
        WHERE project_id = {project_id:String} AND kind = 'generation'
          AND start_time >= {since:DateTime64(3)} AND start_time <= {until:DateTime64(3)}
        GROUP BY user_id ORDER BY cost_usd DESC LIMIT {limit:UInt32}
    """
    return query(client, sql, {"project_id": project_id, "since": since, "until": until,
                               "limit": limit})


def cost_by_model(client, project_id: str, since: datetime, until: datetime):
    sql = """
        SELECT model, sum(cost_usd) AS cost_usd, sum(count) AS requests
        FROM metrics_by_minute
        WHERE project_id = {project_id:String}
          AND minute >= {since:DateTime} AND minute <= {until:DateTime}
        GROUP BY model ORDER BY cost_usd DESC
    """
    return query(client, sql, {"project_id": project_id, "since": since, "until": until})


def top_errors(client, project_id: str, since: datetime, until: datetime, limit: int = 20):
    sql = """
        SELECT status_message, count() AS n, any(model) AS model, max(start_time) AS last_seen
        FROM spans
        WHERE project_id = {project_id:String} AND status = 'error'
          AND start_time >= {since:DateTime64(3)} AND start_time <= {until:DateTime64(3)}
        GROUP BY status_message ORDER BY n DESC LIMIT {limit:UInt32}
    """
    return query(client, sql, {"project_id": project_id, "since": since, "until": until,
                               "limit": limit})
