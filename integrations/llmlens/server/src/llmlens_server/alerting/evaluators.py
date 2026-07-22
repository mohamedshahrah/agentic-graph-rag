"""Compute the current value of an alert rule from ClickHouse, and decide whether
it breaches the threshold."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from llmlens_server.storage.clickhouse import queries


def metric_for_rule(ch_client, rule: dict) -> float:
    until = datetime.now(UTC)
    since = until - timedelta(seconds=int(rule["window_seconds"]))
    ov = queries.metrics_overview(ch_client, rule["project_id"], since, until)
    rule_type = rule["type"]
    if rule_type == "error_rate":
        return float(ov["error_rate"])
    if rule_type == "cost_spike":
        return float(ov["cost_usd"])
    if rule_type == "latency_p95":
        return float(ov["latency_p95"] or 0.0)
    if rule_type == "volume":
        return float(ov["requests"])
    return 0.0


def breached(rule: dict, value: float) -> bool:
    return value > float(rule["threshold"])
