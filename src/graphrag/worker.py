"""Arq worker: runs ingestion off the API process so a big upload never blocks a
request, and so the heavy work runs in a container you can resource-limit
separately.

Run it:  arq graphrag.worker.WorkerSettings
"""

from __future__ import annotations

import asyncio
import os

from arq.connections import RedisSettings

from graphrag.config.settings import Secrets
from graphrag.container import Container
from graphrag.core.logging import get_logger
from graphrag.jobs import JobStatus, JobStore
from graphrag.pipelines import IngestPipeline

log = get_logger(__name__)

# Through Secrets, not raw os.environ — so a bare `arq graphrag.worker...` run
# picks the URL up from .env exactly like every other entrypoint.
_REDIS_URL = Secrets().redis_url


async def ingest_task(ctx: dict, job_id: str, path: str, user_id: str | None) -> None:
    container: Container = ctx["container"]
    store: JobStore = ctx["jobs"]
    store.set(JobStatus(job_id, status="running"))
    try:
        # The pipeline is blocking (embeddings, Neo4j) — run it off the event loop.
        stats = await asyncio.to_thread(IngestPipeline(container).run, path, user_id)
        store.set(
            JobStatus(
                job_id, status="done", documents=stats.documents, chunks=stats.chunks,
                entities=stats.entities, relations=stats.relations,
            )
        )
    except Exception as exc:  # record failure; don't crash the worker
        log.warning("ingest_task_failed", job=job_id, error=str(exc))
        store.set(JobStatus(job_id, status="error", detail=str(exc)))


async def startup(ctx: dict) -> None:
    # Build the container once per worker so models load a single time.
    container = Container()
    ctx["container"] = container
    ctx["jobs"] = JobStore(container.redis)
    log.info("worker_started")


class WorkerSettings:
    functions = [ingest_task]
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(_REDIS_URL)
    max_jobs = int(os.environ.get("GRAPHRAG_WORKER_CONCURRENCY", "2"))
    keep_result = 3600
    job_timeout = int(os.environ.get("GRAPHRAG_JOB_TIMEOUT", "3600"))
