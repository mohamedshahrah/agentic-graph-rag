"""Process configuration — the *deployment* surface.

Two configuration surfaces exist and they do different jobs:

* **This file / the environment (a local ``.env``)** — *where and how the server runs*:
  which judge **model/provider/key** to use, the bind address, the server auth key,
  cache/log knobs. Copy ``.env.example`` to ``.env`` and edit it. Every field below maps
  to an env var named ``GUARD_`` + the field name (e.g. ``llm_model`` -> ``GUARD_LLM_MODEL``).
* **``policies/*.yaml``** — *what the guard actually does*: scope, categories, thresholds,
  redaction, custom rules. See :mod:`guardrails.policy`.

``get_settings()`` is cached so the app reads the environment once at startup.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

FailMode = Literal["open", "closed", "flag"]


class Settings(BaseSettings):
    """Server + judge configuration (env prefix ``GUARD_``)."""

    model_config = SettingsConfigDict(
        env_prefix="GUARD_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── Judge model / provider (set these in .env) ──────────────────────────
    # The "which brain does the reasoning" knobs. Pick a preset with GUARD_LLM_PROVIDER,
    # name the model with GUARD_LLM_MODEL, and supply the key with GUARD_LLM_API_KEY
    # (or the preset's native key env var, e.g. ANTHROPIC_API_KEY / OPENAI_API_KEY).
    llm_provider: str = "anthropic"
    llm_model: str | None = None
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    llm_timeout_s: float = Field(default=10.0, gt=0)
    llm_max_tokens: int = Field(default=1024, gt=0)

    # ── Policy / behaviour ──────────────────────────────────────────────────
    fail_mode: FailMode = "flag"
    policy_dir: str = "./policies"
    default_policy: str = "default"

    # ── Server ──────────────────────────────────────────────────────────────
    api_key: str | None = None
    # Bind to loopback by default: the server is reachable only from this machine and
    # is never exposed on the network. Set GUARD_HOST=0.0.0.0 to expose it (the Docker
    # image does this so the container is reachable via -p).
    host: str = "127.0.0.1"
    port: int = Field(default=8080, ge=1, le=65535)
    # Interactive API docs (/docs, /redoc, /openapi.json). Off by default so the server
    # exposes nothing but the endpoints it serves. Flip to true for local exploration.
    enable_docs: bool = True

    # ── Verdict cache ───────────────────────────────────────────────────────
    cache_enabled: bool = True
    cache_size: int = Field(default=2048, ge=1)
    cache_ttl_s: int = Field(default=300, ge=0)

    # ── Concurrency ─────────────────────────────────────────────────────────
    max_concurrent_judge: int = Field(default=16, ge=1)

    # ── Logging ─────────────────────────────────────────────────────────────
    log_level: str = "info"
    log_verdicts: bool = True
    log_inputs: bool = False


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide, cached :class:`Settings`."""
    return Settings()
