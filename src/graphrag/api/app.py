"""FastAPI application factory.

Run bare:      uvicorn graphrag.api.app:create_app --factory --port 8000
Interactive testing UI is auto-generated at /docs (Swagger) and /redoc.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from graphrag import __version__
from graphrag.auth import KeyStore
from graphrag.container import Container
from graphrag.core.logging import get_logger
from graphrag.jobs import JobStore
from graphrag.pipelines import QueryService

log = get_logger(__name__)


def _rate_key(request: Request) -> str:
    # Rate-limit per user, falling back to client IP for unauthenticated calls.
    return request.headers.get("X-User-Id") or get_remote_address(request)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    container: Container = app.state.container

    if container.secrets.neo4j_password in ("please-change-me", ""):
        log.warning("weak_neo4j_password", hint="set GRAPHRAG_NEO4J_PASSWORD in .env")

    try:
        container.setup_storage()
        log.info("storage_ready", corpus=container.settings.tenancy.default_user)
    except Exception as exc:  # don't crash the API if Neo4j is briefly down
        log.warning("storage_setup_deferred", error=str(exc))

    # The Redis checkpointer is async and has to be initialized on the loop that
    # serves requests — here, not at construction time. It backs both /query
    # paths: the sync one refuses to run until this has happened, and streaming
    # needs its async half. Do it before any request can arrive.
    asetup = getattr(container.checkpointer, "asetup", None)
    if asetup is not None:
        try:
            await asetup()
            log.info("agent_memory_ready", backend="redis")
        except Exception as exc:
            log.warning("agent_memory_setup_failed", error=str(exc))

    # Connect to the ingest queue; fall back to in-process tasks if unavailable.
    app.state.arq = None
    try:
        from arq import create_pool
        from arq.connections import RedisSettings

        app.state.arq = await create_pool(RedisSettings.from_dsn(container.secrets.redis_url))
        log.info("ingest_queue_ready")
    except Exception as exc:
        log.warning("ingest_queue_unavailable", detail="using in-process fallback", error=str(exc))

    yield

    if app.state.arq is not None:
        await app.state.arq.close()


def create_app(container: Container | None = None) -> FastAPI:
    container = container or Container()

    app = FastAPI(
        title="Agentic Graph RAG",
        version=__version__,
        summary="Hybrid knowledge-graph + vector retrieval, driven by a tool-using agent.",
        lifespan=_lifespan,
    )
    app.state.container = container
    app.state.query_service = QueryService(container)
    app.state.job_store = JobStore(container.redis)
    app.state.key_store = KeyStore(container.redis)
    app.state.users = {container.settings.tenancy.default_user}
    if container.settings.auth.enabled:
        log.info("auth_enabled", note="API key required (Authorization: Bearer)")

    # Rate limiting (per user / IP).
    app.state.limiter = Limiter(
        key_func=_rate_key, default_limits=[container.settings.api.rate_limit]
    )
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=container.settings.api.cors_origins,
        allow_methods=container.settings.api.cors_methods,
        allow_headers=container.settings.api.cors_headers,
    )

    from graphrag.api.routers import health, ingest, query, search, users

    app.include_router(health.router)
    app.include_router(users.router)
    app.include_router(ingest.router)
    app.include_router(query.router)
    app.include_router(search.router)
    return app
