"""Storage factories. Backends are chosen by config; Neo4j is the default and
serves as both the graph store and the vector store (one connection)."""

from __future__ import annotations

from graphrag.config.settings import Secrets, Settings
from graphrag.core.errors import ConfigError
from graphrag.storage.graph.base import GraphStore
from graphrag.storage.neo4j_client import driver_from_secrets
from graphrag.storage.vector.base import VectorStore


def build_graph_store(settings: Settings, secrets: Secrets) -> GraphStore:
    if settings.storage.graph.provider == "neo4j":
        from graphrag.storage.graph.neo4j_store import Neo4jGraphStore

        return Neo4jGraphStore(
            driver_from_secrets(secrets), settings.storage.graph.database, settings.app.corpus
        )
    raise ConfigError(f"Unknown graph provider: {settings.storage.graph.provider}")


def build_vector_store(settings: Settings, secrets: Secrets) -> VectorStore:
    if settings.storage.vector.provider == "neo4j":
        from graphrag.storage.vector.neo4j_vector import Neo4jVectorStore

        return Neo4jVectorStore(
            driver_from_secrets(secrets),
            settings.storage.graph.database,
            settings.app.corpus,
            settings.storage.vector.index_name,
            settings.storage.vector.similarity,
        )
    raise ConfigError(f"Unknown vector provider: {settings.storage.vector.provider}")


__all__ = ["GraphStore", "VectorStore", "build_graph_store", "build_vector_store"]
