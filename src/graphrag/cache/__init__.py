"""Redis client factory. Redis backs the embedding cache, LLM/agent memory
(LangGraph checkpointer), and ingest-job status."""

from __future__ import annotations

from functools import lru_cache

from graphrag.core.errors import StorageError


@lru_cache(maxsize=4)
def get_redis(url: str):
    try:
        import redis
    except ImportError as exc:  # pragma: no cover
        raise StorageError("redis package not installed") from exc
    return redis.Redis.from_url(url, decode_responses=True)


__all__ = ["get_redis"]
