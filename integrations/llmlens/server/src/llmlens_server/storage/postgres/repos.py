"""Data-access functions for the Postgres config store. Each takes a psycopg
connection (dict_row)."""

from __future__ import annotations

from typing import Any


# -- projects & keys ----------------------------------------------------------
def create_project(conn, project_id: str, name: str) -> None:
    conn.execute(
        "INSERT INTO projects (id, name) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
        (project_id, name),
    )


def get_project(conn, project_id: str) -> dict | None:
    return conn.execute("SELECT * FROM projects WHERE id = %s", (project_id,)).fetchone()


def list_projects(conn) -> list[dict]:
    return conn.execute("SELECT * FROM projects ORDER BY created_at").fetchall()


def add_api_key(conn, project_id: str, key_hash: str, kind: str = "secret") -> None:
    conn.execute(
        "INSERT INTO api_keys (project_id, key_hash, kind) VALUES (%s, %s, %s) "
        "ON CONFLICT (key_hash) DO NOTHING",
        (project_id, key_hash, kind),
    )


def resolve_project_by_key(conn, key_hash: str) -> str | None:
    row = conn.execute(
        "SELECT project_id FROM api_keys WHERE key_hash = %s", (key_hash,)
    ).fetchone()
    return row["project_id"] if row else None


# -- pricing ------------------------------------------------------------------
def upsert_price(conn, provider: str, model: str, inp: float, out: float) -> None:
    conn.execute(
        "INSERT INTO model_pricing (provider, model, input_per_1k, output_per_1k) "
        "VALUES (%s, %s, %s, %s) "
        "ON CONFLICT (provider, model, effective_from) "
        "DO UPDATE SET input_per_1k = EXCLUDED.input_per_1k, "
        "output_per_1k = EXCLUDED.output_per_1k",
        (provider, model, inp, out),
    )


def load_pricing(conn) -> list[dict]:
    return conn.execute(
        "SELECT DISTINCT ON (provider, model) provider, model, input_per_1k, output_per_1k "
        "FROM model_pricing ORDER BY provider, model, effective_from DESC"
    ).fetchall()


# -- channels & alert rules ---------------------------------------------------
def create_channel(conn, project_id: str, kind: str, target: str) -> int:
    row = conn.execute(
        "INSERT INTO notification_channels (project_id, kind, target) "
        "VALUES (%s, %s, %s) RETURNING id",
        (project_id, kind, target),
    ).fetchone()
    return row["id"]


def get_channel(conn, channel_id: int) -> dict | None:
    return conn.execute(
        "SELECT * FROM notification_channels WHERE id = %s", (channel_id,)
    ).fetchone()


def list_channels(conn, project_id: str) -> list[dict]:
    return conn.execute(
        "SELECT * FROM notification_channels WHERE project_id = %s ORDER BY created_at",
        (project_id,),
    ).fetchall()


def delete_channel(conn, channel_id: int) -> bool:
    row = conn.execute(
        "DELETE FROM notification_channels WHERE id = %s RETURNING id", (channel_id,)
    ).fetchone()
    return row is not None


def create_rule(conn, rule: dict[str, Any]) -> int:
    row = conn.execute(
        "INSERT INTO alert_rules "
        "(project_id, name, type, threshold, window_seconds, cooldown_seconds, channel_id) "
        "VALUES (%(project_id)s, %(name)s, %(type)s, %(threshold)s, %(window_seconds)s, "
        "%(cooldown_seconds)s, %(channel_id)s) RETURNING id",
        rule,
    ).fetchone()
    return row["id"]


def list_rules(conn, project_id: str | None = None, enabled_only: bool = False) -> list[dict]:
    sql = "SELECT * FROM alert_rules"
    clauses, params = [], []
    if project_id:
        clauses.append("project_id = %s")
        params.append(project_id)
    if enabled_only:
        clauses.append("enabled = TRUE")
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY created_at"
    return conn.execute(sql, tuple(params)).fetchall()


def set_rule_enabled(conn, rule_id: int, enabled: bool) -> bool:
    row = conn.execute(
        "UPDATE alert_rules SET enabled = %s WHERE id = %s RETURNING id",
        (enabled, rule_id),
    ).fetchone()
    return row is not None


def delete_rule(conn, rule_id: int) -> bool:
    """Deletes the rule and (via FK cascade) its fired-event history."""
    row = conn.execute(
        "DELETE FROM alert_rules WHERE id = %s RETURNING id", (rule_id,)
    ).fetchone()
    return row is not None


def insert_alert_event(conn, rule_id: int, project_id: str, value: float, message: str) -> None:
    conn.execute(
        "INSERT INTO alert_events (rule_id, project_id, value, message) VALUES (%s, %s, %s, %s)",
        (rule_id, project_id, value, message),
    )


def list_alert_events(conn, project_id: str, limit: int = 50) -> list[dict]:
    return conn.execute(
        "SELECT e.*, r.name AS rule_name, r.type AS rule_type FROM alert_events e "
        "JOIN alert_rules r ON r.id = e.rule_id "
        "WHERE e.project_id = %s ORDER BY e.fired_at DESC LIMIT %s",
        (project_id, limit),
    ).fetchall()
