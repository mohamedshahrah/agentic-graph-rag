"""Password hashing.

Argon2id, the current password-hashing recommendation: memory-hard, so a
stolen database resists GPU cracking in a way SHA-family hashes do not. The
parameters below are argon2-cffi's defaults (64 MiB, 3 passes) — deliberately
not tuned down for the small VPS, because logins are rare and a cheap hash is
worth nothing.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

_hasher = PasswordHasher()

MIN_LENGTH = 10
MAX_LENGTH = 128  # argon2 has no practical cap; this bounds request size


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        _hasher.verify(password_hash, password)
        return True
    except (VerifyMismatchError, InvalidHashError, Exception):
        # Any failure is a failed login. Never leak *why* — "wrong password"
        # versus "corrupt hash" is information an attacker can use.
        return False


def needs_rehash(password_hash: str) -> bool:
    """True when the stored hash used weaker parameters than we use now."""
    try:
        return _hasher.check_needs_rehash(password_hash)
    except Exception:
        return False


def validate_password(password: str) -> str | None:
    """Return a problem description, or None when the password is acceptable.

    Length only. Composition rules ("one symbol, one digit") push people toward
    predictable substitutions without adding real entropy.
    """
    if len(password) < MIN_LENGTH:
        return f"Password must be at least {MIN_LENGTH} characters."
    if len(password) > MAX_LENGTH:
        return f"Password must be at most {MAX_LENGTH} characters."
    return None
