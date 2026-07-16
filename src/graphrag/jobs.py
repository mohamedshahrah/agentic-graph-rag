"""Ingest job status, persisted in Redis so it survives restarts and is visible
across API replicas and the worker. Falls back to an in-process dict when Redis
is unavailable (single-process dev)."""

from __future__ import annotations

import contextlib
import json
from dataclasses import asdict, dataclass

_TTL = 86400  # keep job records for a day


@dataclass
class JobStatus:
    job_id: str
    status: str = "queued"  # queued | running | done | error
    detail: str = ""
    documents: int = 0
    chunks: int = 0
    entities: int = 0
    relations: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


class JobStore:
    def __init__(self, redis_client=None) -> None:
        self._redis = redis_client
        self._mem: dict[str, JobStatus] = {}

    @staticmethod
    def _key(job_id: str) -> str:
        return f"ingest:job:{job_id}"

    def set(self, status: JobStatus) -> None:
        self._mem[status.job_id] = status
        if self._redis is not None:
            with contextlib.suppress(Exception):
                self._redis.setex(self._key(status.job_id), _TTL, json.dumps(status.to_dict()))

    def get(self, job_id: str) -> JobStatus | None:
        if self._redis is not None:
            with contextlib.suppress(Exception):
                raw = self._redis.get(self._key(job_id))
                if raw:
                    return JobStatus(**json.loads(raw))
        return self._mem.get(job_id)
