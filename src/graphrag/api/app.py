"""FastAPI application factory.

Run bare:      uvicorn graphrag.api.app:create_app --factory --port 8000
Interactive testing UI is auto-generated at /docs (Swagger) and /redoc.
"""

from __future__ import annotations

import hashlib
import os
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from graphrag import __version__
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
    """Rate-limit bucket key.

    With auth on, the bucket must not be anything the caller can invent — a
    client that picks its own bucket gets a fresh quota per request. The
    session cookie and API key are both server-issued, so hashing them is
    safe *and* cheap: this runs on every request, so it deliberately avoids
    the database lookup that resolving them to a user id would need.

    Dev mode trusts X-User-Id (that's what it's for).
    """
    container: Container = request.app.state.container
    if container.settings.auth.enabled:
        from graphrag.api.deps import SESSION_COOKIE, extract_key

        token = request.cookies.get(SESSION_COOKIE) or extract_key(request)
        if token:
            return "cred:" + hashlib.sha256(token.encode("utf-8")).hexdigest()[:32]
        return get_remote_address(request)
    return request.headers.get("X-User-Id") or get_remote_address(request)


# Endpoints where a cheap IP-scoped limit is the actual defence: they are
# reachable without credentials, and each one is a guessing surface (a
# password, or a six-digit code).
_AUTH_PATHS = ("/auth/login", "/auth/signup", "/auth/verify", "/auth/resend")


async def _csrf_guard(request: Request, call_next):
    """Reject cross-site state-changing requests that carry a session cookie.

    SameSite=Lax already stops the browser sending the cookie on cross-site
    POSTs; this is the belt to that suspenders, and it covers older browsers.
    Requests authenticated by an API key are unaffected — headers cannot be set
    by a cross-site form, which is what makes CSRF a cookie-only problem.
    """
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return await call_next(request)
    from graphrag.api.deps import SESSION_COOKIE

    if request.cookies.get(SESSION_COOKIE):
        origin = request.headers.get("Origin")
        if origin:
            allowed = request.app.state.container.settings.api.cors_origins
            host = request.headers.get("Host", "")
            same_host = origin.split("//")[-1] == host
            if not same_host and origin not in allowed and "*" not in allowed:
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Cross-site request rejected"},
                )
    return await call_next(request)


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


async def _setup_saver(app: FastAPI, saver) -> None:
    """Open and initialize one checkpointer on the running loop."""
    pool = getattr(saver, "_graphrag_pool", None)
    if pool is not None:  # Postgres: bind the pool to this loop first
        await pool.open()
        app.state.checkpoint_pool = pool
    setup = getattr(saver, "asetup", None) or getattr(saver, "setup", None)
    if setup is not None:
        result = setup()
        if hasattr(result, "__await__"):
            await result


async def _init_agent_memory(app: FastAPI, container: Container) -> None:
    """Initialize the durable checkpointer on the loop that serves requests.

    The async savers connect lazily, so this is where an unusable backend
    actually surfaces — notably the Redis saver against plain Redis, which
    constructs fine and then fails every write with "unknown command 'FT._LIST'".
    So a failure here retries on the other durable backend before settling for
    in-process memory.

    Do all of this *before* the first tenant is built: tenants capture whichever
    saver is current, and memory is a feature, not a prerequisite — a dead
    checkpoint store must not take the API down with it.
    """
    backend = container.settings.agent.memory_backend
    try:
        await _setup_saver(app, container.checkpointer)
        log.info("agent_memory_ready", backend=backend)
        return
    except Exception as exc:
        log.warning("agent_memory_setup_failed", backend=backend, error=str(exc))

    try:
        saver = container.retry_checkpointer(backend)
        await _setup_saver(app, saver)
        log.info("agent_memory_ready", backend="fallback", note=f"{backend} was unusable")
        return
    except Exception as exc:
        log.warning("agent_memory_fallback_failed", error=str(exc))

    from langgraph.checkpoint.memory import MemorySaver

    log.warning("agent_memory_in_process", note="conversations will not survive a restart")
    container.__dict__["checkpointer"] = MemorySaver()
    app.state.checkpoint_pool = None


@asynccontextmanager
async def _lifespan(app: FastAPI):
    container: Container = app.state.container

    if container.secrets.neo4j_password in ("please-change-me", ""):
        log.warning("weak_neo4j_password", hint="set GRAPHRAG_NEO4J_PASSWORD in .env")

    app.state.checkpoint_pool = None
    app.state.db_engine = None
    app.state.db = None

    # Postgres holds accounts, limits, usage and chat history. It is optional
    # only until the account system is switched on; when auth is enabled a
    # missing database is a misconfiguration worth shouting about.
    if container.secrets.database_url:
        try:
            from graphrag.db import build_engine, build_sessionmaker

            app.state.db_engine = build_engine(container.secrets.database_url)
            app.state.db = build_sessionmaker(app.state.db_engine)
            log.info("database_ready")
        except Exception as exc:
            log.warning("database_unavailable", error=str(exc))
    elif container.settings.auth.enabled:
        log.warning("database_missing", hint="set GRAPHRAG_DATABASE_URL — accounts need it")

    # Accounts + API keys. Both read from Postgres, so they are rebuilt here
    # rather than in create_app, where the engine does not exist yet.
    from graphrag.accounts import AccountService, PgKeyStore, build_email_sender

    email_sender = build_email_sender(container.settings, container.secrets)
    app.state.accounts = AccountService(
        app.state.db, container.settings, email_sender, container.redis
    )
    app.state.key_store = PgKeyStore(app.state.db, container.redis)

    # Bootstrap the first admin from configuration: with no admin account and
    # no admin key, the admin surface is locked (fail-closed), and there would
    # be no way in.
    if container.secrets.admin_email and app.state.db is not None:
        try:
            promoted = await app.state.accounts.promote_admin(container.secrets.admin_email)
            if not promoted:
                log.info(
                    "admin_bootstrap_pending",
                    email=container.secrets.admin_email,
                    hint="sign up with this address, then restart to claim admin",
                )
        except Exception as exc:
            log.warning("admin_bootstrap_failed", error=str(exc))

    await _init_agent_memory(app, container)

    try:
        container.setup_storage()
        log.info("storage_ready", corpus=container.settings.tenancy.default_user)
    except Exception as exc:  # don't crash the API if Neo4j is briefly down
        log.warning("storage_setup_deferred", error=str(exc))

    # The ingest queue is opt-in. With the duckdb vector provider the API
    # process must own each tenant's database file, so a second process writing
    # them is not merely unnecessary but unsafe — hence off unless asked for.
    app.state.arq = None
    if _use_worker():
        try:
            from arq import create_pool
            from arq.connections import RedisSettings

            app.state.arq = await create_pool(
                RedisSettings.from_dsn(container.secrets.redis_url)
            )
            log.info("ingest_queue_ready")
        except Exception as exc:
            log.warning(
                "ingest_queue_unavailable", detail="using in-process fallback", error=str(exc)
            )
    else:
        log.info("ingest_inprocess", reason="worker disabled (GRAPHRAG_USE_WORKER=0)")

    yield

    if app.state.arq is not None:
        await app.state.arq.close()
    if app.state.checkpoint_pool is not None:
        await app.state.checkpoint_pool.close()
    if app.state.db_engine is not None:
        await app.state.db_engine.dispose()
    if container.settings.storage.vector.provider == "duckdb":
        from graphrag.storage.vector.duckdb_store import close_all

        close_all()


def _use_worker() -> bool:
    return os.getenv("GRAPHRAG_USE_WORKER", "0").strip().lower() in ("1", "true", "yes")


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
    app.state.users = {container.settings.tenancy.default_user}
    # Real instances are built in the lifespan, once the database engine exists.
    app.state.accounts = None
    app.state.key_store = None
    if container.settings.auth.enabled:
        log.info("auth_enabled", note="session cookie or API key required")
        if not (container.secrets.admin_api_key or container.secrets.admin_email):
            log.warning(
                "admin_access_locked",
                note="auth is on but neither GRAPHRAG_ADMIN_KEY nor "
                     "GRAPHRAG_ADMIN_EMAIL is set — the admin panel is unreachable",
            )

    # Rate limiting (per credential / IP). Redis-backed when available so
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
    app.middleware("http")(_csrf_guard)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=container.settings.api.cors_origins,
        allow_methods=container.settings.api.cors_methods,
        allow_headers=container.settings.api.cors_headers,
        # Session cookies only travel cross-origin with credentials allowed —
        # this is what lets the Vite dev server talk to the API.
        allow_credentials=True,
    )

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    from graphrag.api.routers import auth, health, ingest, query, search, users

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(ingest.router)
    app.include_router(query.router)
    app.include_router(search.router)
    return app
