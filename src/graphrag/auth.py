"""API-key format.

Keys are shown to the caller once and never stored in plaintext — only their
SHA-256 hash is kept, so a leaked database yields nothing usable. The storage
and lookup live in `graphrag.accounts.keys` (Postgres); this module is just the
format, kept separate because both the API and the CLI mint keys.
"""

from __future__ import annotations

import hashlib
import secrets

_KEY_PREFIX = "grk_"


def generate_api_key() -> str:
    return _KEY_PREFIX + secrets.token_urlsafe(32)


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()
