"""Storage factories. Backends are chosen by config; Neo4j is the default and
serves as both the graph store and the vector store (one connection). These are
the seams a new backend plugs into — the container calls them per tenant."""

from __future__ import annotations

from graphrag.config.settings import Settings
from graphrag.core.errors import ConfigError
from graphrag.storage.graph.base import GraphStore
from graphrag.storage.vector.base import VectorStore


def build_graph_store(
    driver, database: str, corpus: str, settings: Settings
) -> GraphStore:
    provider = settings.storage.graph.provider
    if provider == "neo4j":
        from graphrag.storage.graph.neo4j_store import Neo4jGraphStore

        return Neo4jGraphStore(driver, database, corpus)
    raise ConfigError(f"Unknown graph provider: {provider}")


def build_vector_store(
    driver, database: str, corpus: str, settings: Settings
) -> VectorStore:
    cfg = settings.storage.vector
    if cfg.provider == "neo4j":
        from graphrag.storage.vector.neo4j_vector import Neo4jVectorStore

        return Neo4jVectorStore(driver, database, corpus, cfg.index_name, cfg.similarity)
    if cfg.provider == "local":
        from graphrag.storage.vector.local_store import LocalVectorStore

        return LocalVectorStore(cfg.local_dir, database, corpus, cfg.similarity)
    if cfg.provider == "duckdb":
        from graphrag.storage.vector.duckdb_store import DuckDBVectorStore

        return DuckDBVectorStore(
            cfg.duckdb_dir, database, corpus, cfg.similarity, cfg.memory_limit_mb
        )
    raise ConfigError(f"Unknown vector provider: {cfg.provider}")


__all__ = ["GraphStore", "VectorStore", "build_graph_store", "build_vector_store"]
