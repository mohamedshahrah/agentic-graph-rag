"""Usage accounting.

Two destinations, on purpose. Redis counters are what the limit checks read, so
they must be cheap and current. The `usage_events` table is the durable record
the admin charts read — it survives a cache flush and can be aggregated over
arbitrary time ranges, which fixed-window counters cannot.

Recording is best-effort and never blocks a response: usage is billing-adjacent
bookkeeping, not something worth failing an answer the user already received.
"""

from __future__ import annotations

import contextlib
import uuid

from graphrag.core.logging import get_logger
from graphrag.db.engine import session_scope
from graphrag.db.models import UsageEvent
from graphrag.limits.service import LimitService

log = get_logger(__name__)

MESSAGE = "message"
TOKENS_OUT = "tokens_out"
UPLOAD = "upload"
INGEST_CHUNKS = "ingest_chunks"


class UsageRecorder:
    def __init__(self, factory=None, limits: LimitService | None = None) -> None:
        self._factory = factory
        self._limits = limits

    async def record(
        self, user_id: str, kind: str, amount: int = 1, meta: dict | None = None
    ) -> None:
        if amount <= 0:
            return
        if self._limits is not None and kind == TOKENS_OUT:
            self._limits.record_tokens(user_id, amount)

        if self._factory is None:
            return
        try:
            # Dev-mode identities are namespace strings, not account rows;
            # there is nothing to reference and nothing to bill.
            user_uuid = uuid.UUID(str(user_id))
        except (ValueError, AttributeError, TypeError):
            return
        try:
            async with session_scope(self._factory) as s:
                s.add(
                    UsageEvent(
                        user_id=user_uuid, kind=kind, amount=amount, meta=meta or {}
                    )
                )
        except Exception as exc:
            log.warning("usage_record_failed", kind=kind, error=str(exc))


def record_usage(redis_client, user_id: str | None, tokens: int) -> None:
    """Legacy Redis-only token counter, kept so the older /usage report and
    deployments without a database keep working."""
    if redis_client is None or tokens <= 0:
        return
    with contextlib.suppress(Exception):
        redis_client.hincrby("graphrag:usage:tokens", user_id or "default", tokens)
