"""Liveness and readiness probes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from graphrag import __version__
from graphrag.api.deps import get_container
from graphrag.api.schemas import Health, Ready
from graphrag.container import Container

router = APIRouter(tags=["health"])


@router.get("/health", response_model=Health)
def health() -> Health:
    return Health(status="ok", version=__version__)


@router.get("/ready", response_model=Ready)
def ready(container: Container = Depends(get_container)) -> Ready:
    neo4j_ok = _check_neo4j(container)
    redis_ok = container.redis is not None
    return Ready(ready=neo4j_ok, neo4j=neo4j_ok, redis=redis_ok)


def _check_neo4j(container: Container) -> bool:
    try:
        with container.driver.session(
            database=container.settings.storage.graph.database
        ) as session:
            session.run("RETURN 1").consume()
        return True
    except Exception:
        return False
