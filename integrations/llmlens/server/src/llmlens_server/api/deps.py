"""FastAPI dependencies: shared singletons (ClickHouse, Redis, settings) plus
per-request Postgres connections and auth (project key for ingest, admin key for
management/read)."""

from __future__ import annotations

import secrets as pysecrets
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, Request

from llmlens_server.core.keys import hash_key
from llmlens_server.storage import setup_storage
from llmlens_server.storage.clickhouse import get_client
from llmlens_server.storage.postgres import connect, repos


def ensure_storage(app) -> None:
    """Create schemas + the ClickHouse client once. Safe to call repeatedly:
    if a backend was down at startup, the next request retries instead of
    serving 500s forever."""
    if app.state.ch is not None:
        return
    with app.state.ch_lock:
        if app.state.ch is not None:
            return
        settings, secrets = app.state.settings, app.state.secrets
        setup_storage(settings, secrets)
        with connect(secrets.postgres_dsn) as conn:
            repos.create_project(conn, "default", "Default")  # for local / auth-off use
        app.state.ch = get_client(secrets)


def get_range(hours: int = 24) -> tuple[datetime, datetime]:
    """Dashboard time window; `?hours=` selects the look-back (default 24h)."""
    until = datetime.now(UTC)
    return until - timedelta(hours=max(1, hours)), until


def get_settings(request: Request):
    return request.app.state.settings


def get_secrets(request: Request):
    return request.app.state.secrets


def get_ch(request: Request):
    if request.app.state.ch is None:
        try:
            ensure_storage(request.app)
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Storage unavailable") from exc
    return request.app.state.ch


def get_redis_client(request: Request):
    return request.app.state.redis


def get_pg(request: Request) -> Iterator:
    conn = connect(request.app.state.secrets.postgres_dsn)
    try:
        yield conn
    finally:
        conn.close()


def _extract_key(request: Request) -> str | None:
    auth = request.headers.get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.headers.get("X-Api-Key")


def ingest_project(request: Request, pg=Depends(get_pg)) -> str:
    """Resolve the project a batch belongs to from its secret key."""
    if not request.app.state.settings.auth.enabled:
        return "default"
    key = _extract_key(request)
    if not key:
        raise HTTPException(status_code=401, detail="Missing API key")
    project = repos.resolve_project_by_key(pg, hash_key(key))
    if not project:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return project


def require_admin(request: Request) -> None:
    settings = request.app.state.settings
    if not settings.auth.enabled:
        return
    admin = request.app.state.secrets.admin_key
    provided = request.headers.get("X-Admin-Key") or ""
    if not pysecrets.compare_digest(provided.encode(), admin.encode()):
        raise HTTPException(status_code=403, detail="Admin key required")


def read_project(project_id: str = "default", _: None = Depends(require_admin)) -> str:
    """Project scope for dashboard reads (admin-gated when auth is on)."""
    return project_id
