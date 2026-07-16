"""User management. A "user" is an isolated namespace; creating one prepares its
indexes and (when auth is enabled) mints an API key. The registry lives in Redis
(falling back to in-memory)."""

from __future__ import annotations

import contextlib

from fastapi import APIRouter, Depends, Request

from graphrag.api.deps import get_container, get_key_store, require_admin
from graphrag.api.schemas import UserCreate, UserCreated, UsersList
from graphrag.auth import KeyStore
from graphrag.container import Container, sanitize_user

router = APIRouter(tags=["users"])

_REGISTRY_KEY = "graphrag:users"


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
def create_user(
    payload: UserCreate,
    request: Request,
    _: None = Depends(require_admin),
    container: Container = Depends(get_container),
    key_store: KeyStore = Depends(get_key_store),
) -> UserCreated:
    user = sanitize_user(payload.user_id)
    _register(request, container, user)
    container.tenant(user)  # prepare the user's namespace (indexes)

    api_key = key_store.create_key(user) if container.settings.auth.enabled else None
    return UserCreated(user_id=user, api_key=api_key)


@router.get("/users", response_model=UsersList)
def list_users(
    request: Request,
    _: None = Depends(require_admin),
    container: Container = Depends(get_container),
) -> UsersList:
    return UsersList(users=_members(request, container))
