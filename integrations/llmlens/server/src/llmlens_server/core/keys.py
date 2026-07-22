"""API-key generation and hashing. Keys are shown once; only hashes are stored."""

from __future__ import annotations

import hashlib
import secrets


def generate_key(prefix: str = "sk") -> str:
    return f"{prefix}_{secrets.token_urlsafe(24)}"


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()
