"""FastAPI application factory.

Run bare:      uvicorn graphrag.api.app:create_app --factory --port 8000
Interactive testing UI is auto-generated at /docs (Swagger) and /redoc.
"""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
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

_REQUESTS = Counter(
    "graphrag_requests_total", "HTTP requests", ["method", "path", "status"]
)
_LATENCY = Histogram(
    "graphrag_request_seconds", "HTTP request latency", ["method", "path"],
    buckets=(0.05, 0.25, 1, 5, 15, 60, 180),
)


def _rate_key(request: Request) -> str:
    """Rate-limit bucket key. With auth on, the bucket is the *verified* user —
    never a header the caller invents, which would let one client mint a fresh
    bucket per request. Dev mode trusts X-User-Id (that's what it's for)."""
    container: Container = request.app.state.container
    if container.settings.auth.enabled:
        from graphrag.api.deps import extract_key

        key = extract_key(request)
        if key:
            user = request.app.state.key_store.resolve(key)
            if user:
                return f"user:{user}"
        return get_remote_address(request)
    return request.headers.get("X-User-Id") or get_remote_address(request)


# Health/readiness/metrics poll every few seconds and would bury everything else.
_QUIET_PATHS = {"/health", "/ready", "/metrics"}


async def _log_requests(request: Request, call_next):
    """One line in, one line out, per request.

    Without this, "I sent a message and nothing happened" is unanswerable from
    the container: uvicorn only logs a request once it *completes*, so anything
    still running — or a request that never arrived — is invisible. The `started`
    line proves the request reached the API at all, which is the first fork in
    the diagnosis.
    """
    if request.url.path in _QUIET_PATHS:
        return await call_next(request)

    rid = uuid.uuid4().hex[:8]
    started = time.perf_counter()
    log.info(
        "request_started",
        rid=rid,
        method=request.method,
        path=request.url.path,
        user=request.headers.get("X-User-Id", "-"),
    )
    try:
        response = await call_next(request)
    except Exception as exc:
        log.exception(
            "request_failed",
            rid=rid,
            path=request.url.path,
            kind=type(exc).__name__,
            error=str(exc) or type(exc).__name__,
            seconds=round(time.perf_counter() - started, 2),
        )
        _observe(request, 500, time.perf_counter() - started)
        raise
    elapsed = time.perf_counter() - started
    _observe(request, response.status_code, elapsed)
    log.info(
        "request_done",
        rid=rid,
        path=request.url.path,
        status=response.status_code,
        seconds=round(elapsed, 2),
    )
    return response


def _observe(request: Request, status: int, seconds: float) -> None:
    # The route *template* (/ingest/{job_id}), not the raw path — raw paths are
    # unbounded label cardinality, which is how Prometheus dies.
    route = request.scope.get("route")
    path = getattr(route, "path", request.url.path)
    _REQUESTS.labels(request.method, path, str(status)).inc()
    _LATENCY.labels(request.method, path).observe(seconds)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    container: Container = app.state.container

    if container.secrets.neo4j_password in ("please-change-me", ""):
        log.warning("weak_neo4j_password", hint="set GRAPHRAG_NEO4J_PASSWORD in .env")

    # The Redis checkpointer is async and has to be initialized on the loop that
    # serves requests — here, not at construction time. Do it *before* the first
    # tenant is built: if it fails, we swap in in-process memory, and tenants
    # created after this point pick the working saver up.
    asetup = getattr(container.checkpointer, "asetup", None)
    if asetup is not None:
        try:
            await asetup()
            log.info("agent_memory_ready", backend="redis")
        except Exception as exc:
            log.warning(
                "agent_memory_setup_failed", error=str(exc), fallback="in-process"
            )
            from langgraph.checkpoint.memory import MemorySaver

            container.checkpointer = MemorySaver()

    try:
        container.setup_storage()
        log.info("storage_ready", corpus=container.settings.tenancy.default_user)
    except Exception as exc:  # don't crash the API if Neo4j is briefly down
        log.warning("storage_setup_deferred", error=str(exc))

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
    # Must be set before anything touches `container.checkpointer`: the API
    # streams over `astream`, which needs the async saver flavor.
    container.async_memory = True

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
        if not container.secrets.admin_api_key:
            log.warning(
                "admin_key_missing",
                note="auth is on but GRAPHRAG_ADMIN_KEY is unset — "
                     "user creation is locked until it is configured",
            )

    # Rate limiting (per verified user / IP). Redis-backed when available so
    # limits hold across API replicas; in-memory otherwise.
    storage_uri = container.secrets.redis_url if container.redis is not None else "memory://"
    app.state.limiter = Limiter(
        key_func=_rate_key,
        default_limits=[container.settings.api.rate_limit],
        storage_uri=storage_uri,
    )
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)
    app.middleware("http")(_log_requests)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=container.settings.api.cors_origins,
        allow_methods=container.settings.api.cors_methods,
        allow_headers=container.settings.api.cors_headers,
    )

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    from graphrag.api.routers import health, ingest, query, search, users

    app.include_router(health.router)
    app.include_router(users.router)
    app.include_router(ingest.router)
    app.include_router(query.router)
    app.include_router(search.router)
    return app
