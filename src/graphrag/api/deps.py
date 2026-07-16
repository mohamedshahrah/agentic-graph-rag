"""FastAPI dependencies. The Container is built once at startup and shared.

The current user is resolved per request: from a verified API key when
`auth.enabled`, otherwise from the `X-User-Id` header (dev mode)."""

from __future__ import annotations

from fastapi import HTTPException, Request

from graphrag.auth import KeyStore
from graphrag.container import Container
from graphrag.pipelines import QueryService


def get_container(request: Request) -> Container:
    return request.app.state.container


def get_query_service(request: Request) -> QueryService:
    return request.app.state.query_service


def get_job_store(request: Request):
    return request.app.state.job_store


def get_key_store(request: Request) -> KeyStore:
    return request.app.state.key_store


def _extract_key(request: Request) -> str | None:
    auth = request.headers.get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.headers.get("X-API-Key")


def get_current_user(request: Request) -> str | None:
    """Resolve the request's user. Raises 401 when auth is on and the key is
    missing/invalid. Returns None (→ default user) in dev mode with no header."""
    container: Container = request.app.state.container
    if not container.settings.auth.enabled:
        return request.headers.get("X-User-Id")

    key = _extract_key(request)
    if not key:
        raise HTTPException(status_code=401, detail="Missing API key")
    user = request.app.state.key_store.resolve(key)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return user


def require_admin(request: Request) -> None:
    """Gate an operation behind the admin key (only enforced when auth is on and
    an admin key is configured)."""
    container: Container = request.app.state.container
    admin = container.secrets.admin_api_key
    if container.settings.auth.enabled and admin and request.headers.get("X-Admin-Key") != admin:
        raise HTTPException(status_code=403, detail="Admin key required")
