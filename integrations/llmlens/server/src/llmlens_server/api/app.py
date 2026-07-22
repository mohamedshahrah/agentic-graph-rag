"""FastAPI application factory.

Run bare:  uvicorn llmlens_server.api.app:create_app --factory --port 8000
Swagger UI at /docs.
"""

from __future__ import annotations

import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from llmlens_server import __version__
from llmlens_server.api.deps import ensure_storage
from llmlens_server.config import load_settings
from llmlens_server.core.logging import configure_logging, get_logger
from llmlens_server.redis_client import get_redis

log = get_logger(__name__)


def _rate_key(request: Request) -> str:
    return request.headers.get("X-Api-Key") or get_remote_address(request)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    try:
        ensure_storage(app)
        log.info("storage_ready")
    except Exception as exc:  # keep the API up; deps.get_ch retries per request
        log.warning("storage_setup_deferred", error=str(exc))
    yield


def create_app(profile: str | None = None) -> FastAPI:
    settings, secrets = load_settings(profile)
    configure_logging(settings.app.log_level)

    app = FastAPI(
        title="llmlens",
        version=__version__,
        summary="LLM observability: ingest, store, query, and alert on traces.",
        lifespan=_lifespan,
    )
    app.state.settings = settings
    app.state.secrets = secrets
    app.state.redis = get_redis(secrets.redis_url)  # lazy connect (safe at import)
    app.state.ch = None  # set by ensure_storage (lifespan, or first request)
    app.state.ch_lock = threading.Lock()

    app.state.limiter = Limiter(key_func=_rate_key, default_limits=[settings.api.rate_limit])
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.api.cors_origins,
        allow_methods=settings.api.cors_methods,
        allow_headers=settings.api.cors_headers,
    )

    from llmlens_server.api.routers import alerts, health, ingest, metrics, otlp, projects, traces

    for module in (health, ingest, otlp, traces, metrics, projects, alerts):
        app.include_router(module.router)
    return app
