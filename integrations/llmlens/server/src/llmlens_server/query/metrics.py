"""Metric read models — thin wrappers over the ClickHouse aggregation queries
(most of which read the pre-aggregated materialized view)."""

from __future__ import annotations

from datetime import datetime

from llmlens_server.storage.clickhouse import queries


def overview(ch_client, project_id: str, since: datetime, until: datetime) -> dict:
    return queries.metrics_overview(ch_client, project_id, since, until)


def timeseries(ch_client, project_id: str, since: datetime, until: datetime) -> list[dict]:
    return queries.metrics_timeseries(ch_client, project_id, since, until)


def cost_by_user(ch_client, project_id: str, since: datetime, until: datetime) -> list[dict]:
    return queries.cost_by_user(ch_client, project_id, since, until)


def cost_by_model(ch_client, project_id: str, since: datetime, until: datetime) -> list[dict]:
    return queries.cost_by_model(ch_client, project_id, since, until)


def top_errors(ch_client, project_id: str, since: datetime, until: datetime) -> list[dict]:
    return queries.top_errors(ch_client, project_id, since, until)
