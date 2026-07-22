"""Observability layer — the llmlens integration.

The agent is a LangChain/LangGraph app, so a single call to the llmlens SDK's
LangChain instrumentation captures every agent run, LLM call, retriever and tool
call — with timing, tokens, cost and errors — and ships them to the standalone
**llmlens** server (vendored under `integrations/llmlens`, its own repo).

Two entry points:

* `setup_observability(settings, secrets)` — called once at API startup. Reads
  `observability.enabled`; when on, configures the SDK and registers the global
  LangChain handler. Never raises: a missing SDK or a down collector must not
  stop the API from serving.
* `query_trace(name, user_id=...)` — an optional root span per request so cost
  and latency can be attributed **per user** in the llmlens dashboard. A no-op
  (`nullcontext`) unless observability was successfully set up.
"""

from __future__ import annotations

import contextlib
from typing import Any

from graphrag.core.logging import get_logger

log = get_logger(__name__)

# Flipped True once the SDK is configured and instrumented. `query_trace` reads
# it so that, when observability is off, it stays a pure no-op and never imports
# or drives the SDK.
_ACTIVE = False


def is_active() -> bool:
    return _ACTIVE


def setup_observability(settings: Any, secrets: Any) -> bool:
    """Configure llmlens and instrument LangChain. Returns whether it turned on.

    Safe to call when the feature is off, the SDK isn't installed, or the
    collector is unreachable — each case logs and returns False.
    """
    global _ACTIVE
    cfg = getattr(settings, "observability", None)
    if cfg is None or not cfg.enabled:
        log.info("observability_disabled")
        return False

    try:
        import llmlens
    except ImportError:
        log.warning(
            "observability_sdk_missing",
            hint="pip install -e integrations/llmlens/sdk  (or add it to the image)",
        )
        return False

    try:
        # The SDK also reads LLMLENS_URL / LLMLENS_API_KEY from the environment;
        # pass them explicitly when provided so YAML config wins over stray env.
        kwargs: dict[str, Any] = {}
        url = getattr(secrets, "llmlens_url", None) or cfg.url
        if url:
            kwargs["url"] = url
        if getattr(secrets, "llmlens_api_key", None):
            kwargs["api_key"] = secrets.llmlens_api_key
        llmlens.configure(**kwargs)

        result = llmlens.instrument("langchain")
        if not result.get("langchain"):
            # langchain-core is a hard dependency of this app, so this should not
            # happen — but if the SDK couldn't register the hook, tracing is off.
            log.warning("observability_langchain_unavailable")
            return False
    except Exception as exc:  # never let telemetry setup break startup
        log.warning("observability_setup_failed", error=str(exc) or type(exc).__name__)
        return False

    _ACTIVE = True
    log.info("observability_ready", url=url, service=cfg.service)
    return True


def query_trace(name: str, *, user_id: str | None = None):
    """A root llmlens span for one request, or a no-op when observability is off.

    Wrapping the agent run attributes its child spans (the auto-traced LangChain
    calls) to a `user_id`, which is what powers cost-per-user in the dashboard.
    """
    if not _ACTIVE:
        return contextlib.nullcontext()
    import llmlens

    return llmlens.trace(name, user_id=user_id)


__all__ = ["setup_observability", "query_trace", "is_active"]
