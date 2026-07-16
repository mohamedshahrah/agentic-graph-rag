"""A Redis-backed cache wrapper around any Embedder. Identical (model, text)
pairs are embedded once and reused — big savings on re-ingest and repeat queries."""

from __future__ import annotations

import hashlib
import json

from graphrag.embeddings.base import Embedder


class CachedEmbedder(Embedder):
    def __init__(self, inner: Embedder, redis_client, model: str, ttl: int) -> None:
        self._inner = inner
        self._redis = redis_client
        self._model = model
        self._ttl = ttl
        self.dim = inner.dim

    def _key(self, text: str) -> str:
        h = hashlib.sha1(f"{self._model}::{text}".encode()).hexdigest()
        return f"emb:{h}"

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        keys = [self._key(t) for t in texts]
        cached = self._redis.mget(keys)
        results: list[list[float] | None] = [
            json.loads(c) if c else None for c in cached
        ]

        missing = [i for i, r in enumerate(results) if r is None]
        if missing:
            fresh = self._inner.embed_documents([texts[i] for i in missing])
            pipe = self._redis.pipeline()
            for idx, vec in zip(missing, fresh, strict=True):
                results[idx] = vec
                pipe.setex(keys[idx], self._ttl, json.dumps(vec))
            pipe.execute()
        return [r for r in results if r is not None]

    def embed_query(self, text: str) -> list[float]:
        key = self._key("q::" + text)
        hit = self._redis.get(key)
        if hit:
            return json.loads(hit)
        vec = self._inner.embed_query(text)
        self._redis.setex(key, self._ttl, json.dumps(vec))
        return vec
