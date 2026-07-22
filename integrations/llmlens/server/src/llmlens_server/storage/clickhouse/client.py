"""ClickHouse connection + schema application. Uses clickhouse-connect."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from llmlens_server.config.settings import Secrets, Settings
from llmlens_server.core.errors import StorageError

_SQL_DIR = Path(__file__).resolve().parent


def _connect(secrets: Secrets, database: str | None):
    try:
        import clickhouse_connect
    except ImportError as exc:  # pragma: no cover
        raise StorageError("clickhouse-connect not installed") from exc
    return clickhouse_connect.get_client(
        host=secrets.clickhouse_host,
        port=secrets.clickhouse_port,
        username=secrets.clickhouse_user,
        password=secrets.clickhouse_password,
        database=database,
    )


def get_client(secrets: Secrets):
    """A client bound to the llmlens database."""
    return _connect(secrets, secrets.clickhouse_db)


def _statements(sql: str) -> list[str]:
    # Strip comment LINES first, then split. Filtering ";"-chunks that *start*
    # with "--" would drop entire statements that merely follow a comment block
    # (and a ";" inside a comment would corrupt the next statement).
    sql = re.sub(r"^\s*--.*$", "", sql, flags=re.MULTILINE)
    return [s.strip() for s in sql.split(";") if s.strip()]


def apply_schema(settings: Settings, secrets: Secrets) -> None:
    """Create the database, tables, and materialized views (idempotent)."""
    admin = _connect(secrets, None)
    admin.command(f"CREATE DATABASE IF NOT EXISTS {secrets.clickhouse_db}")

    client = get_client(secrets)
    retention = int(settings.app.retention_days)
    for fname in ("schema.sql", "matviews.sql"):
        sql = (_SQL_DIR / fname).read_text(encoding="utf-8")
        sql = sql.replace("{{RETENTION_DAYS}}", str(retention))
        for stmt in _statements(sql):
            client.command(stmt)


def insert_rows(client, table: str, column_names: list[str], rows: list[tuple]) -> None:
    if not rows:
        return
    client.insert(table, rows, column_names=column_names, settings={"async_insert": 1})


def query(client, sql: str, parameters: dict | None = None) -> list[dict]:
    result = client.query(sql, parameters=parameters or {})
    cols = result.column_names
    rows = [dict(zip(cols, row, strict=True)) for row in result.result_rows]
    # ClickHouse DateTime columns come back tz-naive (in UTC). Tag them so JSON
    # responses carry an offset — otherwise browsers parse them as local time.
    for row in rows:
        for key, val in row.items():
            if isinstance(val, datetime) and val.tzinfo is None:
                row[key] = val.replace(tzinfo=UTC)
    return rows
