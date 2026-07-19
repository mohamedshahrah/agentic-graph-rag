"""Initial schema: accounts, limits, usage, chat history, files, operations.

Revision ID: 0001
Revises:
Create Date: 2026-07-19
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def _ts(name: str, **kw) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), **kw)


def _created_at() -> sa.Column:
    return _ts("created_at", server_default=sa.text("now()"), nullable=False)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text, nullable=False),
        sa.Column("tenant_id", sa.String(48), nullable=False, unique=True),
        sa.Column("role", sa.String(16), nullable=False, server_default="user"),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        _ts("email_verified_at"),
        _ts("last_login_at"),
        _created_at(),
        sa.CheckConstraint("role in ('user','admin')", name="ck_users_role"),
        sa.CheckConstraint(
            "status in ('pending','active','suspended','deleted')", name="ck_users_status"
        ),
    )

    op.create_table(
        "email_otps",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code_hash", sa.Text, nullable=False),
        sa.Column("purpose", sa.String(16), nullable=False, server_default="verify"),
        _ts("expires_at", nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        _ts("consumed_at"),
        _created_at(),
    )
    op.create_index("ix_email_otps_user_id", "email_otps", ["user_id"])

    op.create_table(
        "sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.Text, nullable=False, unique=True),
        _ts("expires_at", nullable=False),
        _ts("last_seen_at"),
        _ts("revoked_at"),
        sa.Column("ip", postgresql.INET),
        sa.Column("user_agent", sa.Text),
        _created_at(),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])

    op.create_table(
        "api_keys",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key_hash", sa.Text, nullable=False, unique=True),
        sa.Column("label", sa.String(64), nullable=False, server_default=""),
        _ts("last_used_at"),
        _ts("revoked_at"),
        _created_at(),
    )
    op.create_index("ix_api_keys_user_id", "api_keys", ["user_id"])

    op.create_table(
        "global_limits",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("messages_per_minute", sa.Integer, nullable=False, server_default="6"),
        sa.Column("messages_per_day", sa.Integer, nullable=False, server_default="100"),
        sa.Column("tokens_per_day", sa.BigInteger, nullable=False, server_default="150000"),
        sa.Column("tokens_per_month", sa.BigInteger, nullable=False, server_default="2000000"),
        sa.Column("max_files", sa.Integer, nullable=False, server_default="10"),
        sa.Column("max_file_mb", sa.Integer, nullable=False, server_default="15"),
        sa.Column("max_storage_mb", sa.Integer, nullable=False, server_default="100"),
        sa.Column("max_chunks", sa.Integer, nullable=False, server_default="20000"),
        sa.Column("max_threads", sa.Integer, nullable=False, server_default="25"),
        _ts("updated_at", server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_global_limits_singleton"),
    )
    # Seed the singleton so the limit service always finds defaults, even
    # before an admin has opened the panel.
    op.execute("INSERT INTO global_limits (id) VALUES (1)")

    op.create_table(
        "user_limits",
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("messages_per_minute", sa.Integer),
        sa.Column("messages_per_day", sa.Integer),
        sa.Column("tokens_per_day", sa.BigInteger),
        sa.Column("tokens_per_month", sa.BigInteger),
        sa.Column("max_files", sa.Integer),
        sa.Column("max_file_mb", sa.Integer),
        sa.Column("max_storage_mb", sa.Integer),
        sa.Column("max_chunks", sa.Integer),
        sa.Column("max_threads", sa.Integer),
        _ts("updated_at", server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "usage_events",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("amount", sa.BigInteger, nullable=False, server_default="1"),
        sa.Column("meta", postgresql.JSONB, nullable=False, server_default="{}"),
        _created_at(),
    )
    op.create_index("ix_usage_user_time", "usage_events", ["user_id", "created_at"])
    op.create_index("ix_usage_time", "usage_events", ["created_at"])

    op.create_table(
        "threads",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(120), nullable=False, server_default="New chat"),
        _ts("deleted_at"),
        _created_at(),
        _ts("updated_at", server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_threads_user", "threads", ["user_id", "updated_at"])

    op.create_table(
        "messages",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("thread_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("threads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(12), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("sources", postgresql.JSONB),
        sa.Column("tool_calls", postgresql.JSONB),
        sa.Column("model", sa.String(64)),
        _created_at(),
        sa.CheckConstraint("role in ('user','assistant')", name="ck_messages_role"),
    )
    op.create_index("ix_messages_thread", "messages", ["thread_id", "id"])

    op.create_table(
        "files",
        sa.Column("id", sa.String(16), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("path", sa.Text, nullable=False),
        sa.Column("size_bytes", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("mime", sa.String(64)),
        sa.Column("status", sa.String(16), nullable=False, server_default="uploaded"),
        sa.Column("chunks", sa.Integer, nullable=False, server_default="0"),
        sa.Column("job_id", sa.String(16)),
        _created_at(),
    )
    op.create_index("ix_files_user_id", "files", ["user_id"])

    op.create_table(
        "ingest_jobs",
        sa.Column("id", sa.String(16), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("file_id", sa.String(16)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("stats", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("error", sa.Text),
        _ts("started_at"),
        _ts("finished_at"),
    )

    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", postgresql.JSONB, nullable=False),
        _ts("updated_at", server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True)),
        sa.Column("action", sa.String(48), nullable=False),
        sa.Column("target_user_id", postgresql.UUID(as_uuid=True)),
        sa.Column("detail", postgresql.JSONB, nullable=False, server_default="{}"),
        _created_at(),
    )
    op.create_index("ix_audit_time", "audit_log", ["created_at"])


def downgrade() -> None:
    for table in (
        "audit_log", "app_settings", "ingest_jobs", "files", "messages", "threads",
        "usage_events", "user_limits", "global_limits", "api_keys", "sessions",
        "email_otps", "users",
    ):
        op.drop_table(table)
