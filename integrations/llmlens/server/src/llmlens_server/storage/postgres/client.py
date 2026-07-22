"""Postgres connection + schema application (psycopg 3)."""

from __future__ import annotations

from pathlib import Path

from llmlens_server.core.errors import StorageError

_SQL_DIR = Path(__file__).resolve().parent


def connect(dsn: str):
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:  # pragma: no cover
        raise StorageError("psycopg not installed") from exc
    return psycopg.connect(dsn, row_factory=dict_row, autocommit=True)


def apply_schema(dsn: str) -> None:
    sql = (_SQL_DIR / "schema.sql").read_text(encoding="utf-8")
    with connect(dsn) as conn:
        conn.execute(sql)
