"""API-key authentication.

Keys are shown to the caller once and never stored in plaintext — only their
SHA-256 hash is kept (in Redis, with an in-memory fallback). A verified key maps
to a user, so the tenant identity is trustworthy (unlike a raw X-User-Id header).
"""

from __future__ import annotations

import hashlib
import secrets

_KEY_PREFIX = "grk_"
_HASH_MAP = "graphrag:apikeys"  # redis hash: key_hash -> user_id


def generate_api_key() -> str:
    return _KEY_PREFIX + secrets.token_urlsafe(32)


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


class KeyStore:
    def __init__(self, redis_client=None) -> None:
        self._redis = redis_client
        self._mem: dict[str, str] = {}  # key_hash -> user_id

    def create_key(self, user_id: str) -> str:
        """Mint a new key for a user and return it (once)."""
        key = generate_api_key()
        h = hash_key(key)
        self._mem[h] = user_id
        if self._redis is not None:
            self._redis.hset(_HASH_MAP, h, user_id)
            self._redis.sadd(f"graphrag:userkeys:{user_id}", h)
        return key

    def resolve(self, key: str) -> str | None:
        """Return the user id for a valid key, or None."""
        h = hash_key(key)
        if self._redis is not None:
            user = self._redis.hget(_HASH_MAP, h)
            if user:
                return user
        return self._mem.get(h)

    def revoke_user(self, user_id: str) -> int:
        """Revoke all keys for a user. Returns how many were removed."""
        removed = 0
        if self._redis is not None:
            hashes = self._redis.smembers(f"graphrag:userkeys:{user_id}")
            for h in hashes:
                self._redis.hdel(_HASH_MAP, h)
                self._mem.pop(h, None)
                removed += 1
            self._redis.delete(f"graphrag:userkeys:{user_id}")
        else:
            for h in [h for h, u in self._mem.items() if u == user_id]:
                self._mem.pop(h, None)
                removed += 1
        return removed
