"""FastAPI dependencies. The Container is built once at startup and shared.

The current user is resolved per request, in this order:

1. a session cookie (the browser UI),
2. an API key header (programmatic clients — unchanged contract),
3. the `X-User-Id` header, but only in dev mode with auth disabled.

Everything downstream takes an `AuthUser`, whose `tenant_id` is the storage
namespace. Routers must scope by `user.tenant_id` and never by anything the
caller supplied directly.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, Request

from graphrag.container import Container, sanitize_user
from graphrag.pipelines import QueryService

SESSION_COOKIE = "graphrag_session"


@dataclass(frozen=True)
class AuthUser:
    """Who is making this request, and where their data lives."""

    user_id: str
    tenant_id: str
    role: str = "user"
    email: str = ""

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def get_container(request: Request) -> Container:
    return request.app.state.container


def get_query_service(request: Request) -> QueryService:
    return request.app.state.query_service


def get_job_store(request: Request):
    return request.app.state.job_store


def get_key_store(request: Request):
    return request.app.state.key_store


def get_accounts(request: Request):
    return request.app.state.accounts


def get_db(request: Request):
    return request.app.state.db


def extract_key(request: Request) -> str | None:
    auth = request.headers.get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.headers.get("X-API-Key")


async def resolve_user(request: Request) -> AuthUser | None:
    """Identify the caller, or None when unauthenticated.

    Never raises — `get_current_user` decides whether anonymous is acceptable.
    """
    container: Container = request.app.state.container

    token = request.cookies.get(SESSION_COOKIE)
    accounts = getattr(request.app.state, "accounts", None)
    if token and accounts is not None:
        principal = await accounts.resolve_session(token)
        if principal is not None:
            return AuthUser(
                principal.user_id, principal.tenant_id, principal.role, principal.email
            )

    key = extract_key(request)
    key_store = getattr(request.app.state, "key_store", None)
    if key and key_store is not None:
        owner = await key_store.resolve(key)
        if owner is not None:
            return AuthUser(owner.user_id, owner.tenant_id, owner.role, owner.email)

    if not container.settings.auth.enabled:
        # Dev mode: the header is the identity. Sanitized because it becomes a
        # corpus name and a filename.
        header = request.headers.get("X-User-Id")
        tenant = sanitize_user(header or container.settings.tenancy.default_user)
        return AuthUser(user_id=tenant, tenant_id=tenant, role="dev")

    return None


async def get_current_user(request: Request) -> AuthUser:
    """Require an identified caller. 401 when auth is on and none was found."""
    user = await resolve_user(request)
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Sign in, or send an API key (Authorization: Bearer ...)",
        )
    return user


async def require_admin_user(request: Request) -> AuthUser | None:
    """Gate admin surfaces.

    Two ways in: an account with the admin role, or the `X-Admin-Key` break
    glass, which still works when no admin account exists yet (bootstrap) or
    when the account system is down.

    Fail closed: with auth enabled and neither an admin account nor an admin
    key configured, admin endpoints are *locked*, not open — otherwise anyone
    could mint themselves a key and the requirement would be decorative. Dev
    mode (auth off) stays open.
    """
    container: Container = request.app.state.container
    admin_key = container.secrets.admin_api_key
    supplied = request.headers.get("X-Admin-Key")
    if admin_key and supplied and _constant_eq(supplied, admin_key):
        return None  # authenticated as the break-glass admin, no account

    user = await resolve_user(request)
    if user is not None and user.is_admin:
        return user

    if not container.settings.auth.enabled:
        return user  # dev mode

    if not admin_key and user is None:
        raise HTTPException(
            status_code=403,
            detail="Admin access is locked: set GRAPHRAG_ADMIN_KEY or promote an admin account",
        )
    raise HTTPException(status_code=403, detail="Admin access required")


def _constant_eq(a: str, b: str) -> bool:
    import secrets

    return secrets.compare_digest(a, b)
