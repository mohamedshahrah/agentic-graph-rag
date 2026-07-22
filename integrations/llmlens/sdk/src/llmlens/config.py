"""SDK configuration. Reads env by default; override with `configure(...)`."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    """A malformed env var must never crash the host app at import time."""
    val = os.getenv(name)
    if val is None:
        return default
    try:
        return float(val)
    except ValueError:
        return default


@dataclass
class Config:
    api_key: str = ""
    url: str = "http://localhost:8000"
    enabled: bool = True
    record_content: bool = True
    sample_rate: float = 1.0       # head sampling: fraction of traces kept
    flush_interval: float = 1.0    # seconds between exporter flushes
    batch_size: int = 200
    max_queue: int = 10000         # bounded — drop rather than grow unbounded

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            api_key=os.getenv("LLMLENS_API_KEY", ""),
            url=os.getenv("LLMLENS_URL", "http://localhost:8000"),
            enabled=_env_bool("LLMLENS_ENABLED", True),
            record_content=_env_bool("LLMLENS_RECORD_CONTENT", True),
            sample_rate=min(1.0, max(0.0, _env_float("LLMLENS_SAMPLE_RATE", 1.0))),
        )


_config = Config.from_env()


def configure(**kwargs) -> Config:
    """Override configuration. Only provided (non-None) values change."""
    for key, value in kwargs.items():
        if value is not None and hasattr(_config, key):
            setattr(_config, key, value)
    return _config


def get_config() -> Config:
    return _config
