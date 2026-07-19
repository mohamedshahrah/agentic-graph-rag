"""Database URL forms.

Three consumers want three different spellings of the same URL, and getting one
wrong fails at connect time with an unhelpful message — psycopg in particular
rejects SQLAlchemy's `+driver` marker with 'missing "=" in connection info'.
"""

import pytest

from graphrag.core.errors import ConfigError
from graphrag.db.engine import build_engine, libpq_dsn, normalize_dsn, sync_dsn

PLAIN = "postgresql://u:p@host:5432/db"


def test_plain_url_gets_the_async_driver():
    assert normalize_dsn(PLAIN) == "postgresql+asyncpg://u:p@host:5432/db"


def test_heroku_style_postgres_scheme_is_accepted():
    """Hosting panels hand out `postgres://`, which SQLAlchemy rejects."""
    assert normalize_dsn("postgres://u:p@host/db") == "postgresql+asyncpg://u:p@host/db"


def test_already_async_url_is_unchanged():
    url = "postgresql+asyncpg://u:p@host/db"
    assert normalize_dsn(url) == url


def test_alembic_gets_the_sync_sqlalchemy_form():
    assert sync_dsn(PLAIN) == "postgresql+psycopg://u:p@host:5432/db"


def test_checkpointer_gets_a_bare_libpq_conninfo():
    """psycopg parses libpq conninfo and chokes on any `+driver` suffix."""
    assert libpq_dsn(PLAIN) == PLAIN
    assert libpq_dsn("postgresql+asyncpg://u:p@host/db") == "postgresql://u:p@host/db"
    assert "+" not in libpq_dsn(sync_dsn(PLAIN))


def test_credentials_survive_the_round_trip():
    url = "postgresql://user:p%40ss@db.internal:5432/graphrag"
    for form in (normalize_dsn(url), sync_dsn(url), libpq_dsn(url)):
        assert "user:p%40ss@db.internal:5432/graphrag" in form


def test_missing_url_is_a_config_error_not_a_crash():
    with pytest.raises(ConfigError, match="GRAPHRAG_DATABASE_URL"):
        build_engine(None)


def test_engine_pool_is_small_enough_for_a_shared_postgres():
    engine = build_engine(PLAIN)
    assert engine.pool.size() <= 5
