"""Legacy user management.

Accounts are created by signing up (`/auth/signup`); these endpoints remain for
the admin-key workflow and for scripts written against the older API. `/usage`
is superseded by the admin dashboard's aggregates but still reports the raw
Redis token counters.
"""

from __future__ import annotations

import contextlib

from fastapi import APIRouter, Depends, HTTPException, Request

from graphrag.api.deps import AuthUser, get_container, get_key_store, require_admin_user
from graphrag.api.schemas import (
    KeysRevoked,
    UsageReport,
    UserCreate,
    UserCreated,
    UsersList,
)
from graphrag.container import Container, sanitize_user

router = APIRouter(tags=["users"])

_REGISTRY_KEY = "graphrag:users"
_USAGE_KEY = "graphrag:usage:tokens"


def _register(request: Request, container: Container, user: str) -> None:
    if container.redis is not None:
        container.redis.sadd(_REGISTRY_KEY, user)
    request.app.state.users.add(user)


def _members(request: Request, container: Container) -> list[str]:
    users = set(request.app.state.users)
    if container.redis is not None:
        with contextlib.suppress(Exception):
            users |= set(container.redis.smembers(_REGISTRY_KEY))
    return sorted(users)


@router.post("/users", response_model=UserCreated)
async def create_user(
    payload: UserCreate,
    request: Request,
    _: AuthUser | None = Depends(require_admin_user),
    container: Container = Depends(get_container),
) -> UserCreated:
    """Prepare a bare namespace (indexes only), with no login attached.

    Real accounts come from /auth/signup — they have an email, a password and a
    verified address. This exists for scripted single-tenant setups; with auth
    enabled it cannot mint a key, because keys now belong to an account row.
    """
    user = sanitize_user(payload.user_id)
    _register(request, container, user)
    container.tenant(user)  # prepare the user's namespace (indexes)

    if container.settings.auth.enabled:
        raise HTTPException(
            status_code=400,
            detail="With auth enabled, create accounts via /auth/signup "
                   "(keys are issued from /auth/keys).",
        )
    return UserCreated(user_id=user, api_key=None)


@router.get("/users", response_model=UsersList)
async def list_users(
    request: Request,
    _: AuthUser | None = Depends(require_admin_user),
    container: Container = Depends(get_container),
) -> UsersList:
    return UsersList(users=_members(request, container))


@router.delete("/users/{user_id}/keys", response_model=KeysRevoked)
async def revoke_keys(
    user_id: str,
    _: AuthUser | None = Depends(require_admin_user),
    key_store=Depends(get_key_store),
) -> KeysRevoked:
    """Revoke every API key a user holds (their data stays). The way to cut off
    a leaked key: revoke, then mint a fresh one via /auth/keys."""
    revoked = await key_store.revoke_user(user_id)
    return KeysRevoked(user_id=user_id, revoked=revoked)


@router.get("/usage", response_model=UsageReport)
async def usage(
    _: AuthUser | None = Depends(require_admin_user),
    container: Container = Depends(get_container),
) -> UsageReport:
    """Per-user streamed-token counts (approximate — one SSE chunk ≈ one token)."""
    r = container.redis
    if r is None:
        return UsageReport(tokens={})
    raw = r.hgetall(_USAGE_KEY) or {}
    return UsageReport(tokens={k: int(v) for k, v in raw.items()})
