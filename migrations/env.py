"""Alembic environment.

Runs migrations with the sync psycopg driver even though the app uses asyncpg —
migrations are a one-shot startup step, and the sync path keeps this file
simple. The URL always comes from GRAPHRAG_DATABASE_URL.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from graphrag.config.settings import Secrets
from graphrag.db.engine import sync_dsn
from graphrag.db.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _url() -> str:
    secrets = Secrets()
    if not secrets.database_url:
        raise RuntimeError("GRAPHRAG_DATABASE_URL is not set")
    return sync_dsn(secrets.database_url)


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
