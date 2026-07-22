"""The SQL files are applied statement-by-statement through _statements();
comment blocks (and semicolons inside comments) must never swallow or corrupt
a CREATE statement."""

from pathlib import Path

import llmlens_server.storage.clickhouse as ch_pkg
from llmlens_server.storage.clickhouse.client import _statements

_SQL_DIR = Path(ch_pkg.__file__).resolve().parent


def test_schema_sql_keeps_both_create_tables():
    stmts = _statements((_SQL_DIR / "schema.sql").read_text(encoding="utf-8"))
    assert len(stmts) == 2
    assert all(s.upper().startswith("CREATE TABLE") for s in stmts)
    assert "spans" in stmts[0] and "span_content" in stmts[1]


def test_matviews_sql_keeps_table_then_view():
    stmts = _statements((_SQL_DIR / "matviews.sql").read_text(encoding="utf-8"))
    assert len(stmts) == 2
    assert stmts[0].upper().startswith("CREATE TABLE")
    assert stmts[1].upper().startswith("CREATE MATERIALIZED VIEW")


def test_comment_only_input_yields_nothing():
    assert _statements("-- just a comment;\n-- another\n") == []
