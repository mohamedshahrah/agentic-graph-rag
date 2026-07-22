from __future__ import annotations

import contextlib

from fastapi import APIRouter, Request

from llmlens_server import __version__
from llmlens_server.api.schemas import Health, Ready

router = APIRouter(tags=["health"])


@router.get("/health", response_model=Health)
def health() -> Health:
    return Health(status="ok", version=__version__)


@router.get("/ready", response_model=Ready)
def ready(request: Request) -> Ready:
    ch_ok = pg_ok = redis_ok = False
    with contextlib.suppress(Exception):
        request.app.state.ch.command("SELECT 1")
        ch_ok = True
    with contextlib.suppress(Exception):
        from llmlens_server.storage.postgres import connect

        with connect(request.app.state.secrets.postgres_dsn) as conn:
            conn.execute("SELECT 1")
        pg_ok = True
    with contextlib.suppress(Exception):
        request.app.state.redis.ping()
        redis_ok = True
    return Ready(
        ready=ch_ok and pg_ok and redis_ok,
        clickhouse=ch_ok, postgres=pg_ok, redis=redis_ok,
    )
