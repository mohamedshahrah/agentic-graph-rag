"""Shared Neo4j driver. The graph store and vector store both use one connection."""

from __future__ import annotations

from functools import lru_cache

from graphrag.config.settings import Secrets
from graphrag.core.errors import StorageError


@lru_cache(maxsize=4)
def get_driver(uri: str, user: str, password: str):
    try:
        from neo4j import GraphDatabase
    except ImportError as exc:  # pragma: no cover
        raise StorageError("neo4j driver not installed") from exc
    return GraphDatabase.driver(uri, auth=(user, password))


def driver_from_secrets(secrets: Secrets):
    return get_driver(secrets.neo4j_uri, secrets.neo4j_user, secrets.neo4j_password)


def safe_ident(name: str) -> str:
    """Validate an identifier we must interpolate into DDL (index names)."""
    if not name.replace("_", "").isalnum():
        raise StorageError(f"Unsafe identifier: {name!r}")
    return name
