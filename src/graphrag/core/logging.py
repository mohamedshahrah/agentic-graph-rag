"""Structured logging setup. Call `configure_logging(level)` once at startup."""

from __future__ import annotations

import logging
import sys

import structlog

# httpx logs a line per HTTP call at INFO. Reranking alone makes one per
# candidate, so the app's own logs get buried under hundreds of
# "HTTP Request: POST .../api/chat 200 OK". Raise the level to see them again
# (they're genuinely useful when a provider misbehaves) — but not by default,
# because a log nobody can read is the same as no log.
_NOISY = ("httpx", "httpcore", "urllib3", "neo4j.notifications")


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level.upper())
    if level.upper() != "DEBUG":
        for name in _NOISY:
            logging.getLogger(name).setLevel(logging.WARNING)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty()),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level.upper())),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
