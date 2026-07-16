"""Server-Sent Events for streaming answers. The client receives incremental
`token` events, then one `sources` event, then `done`."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator

from graphrag.api.schemas import Source
from graphrag.core.logging import get_logger
from graphrag.pipelines import QueryService

log = get_logger(__name__)


async def sse_answer(
    service: QueryService, question: str, style: str, thread_id: str, user_id: str | None = None
) -> AsyncIterator[dict]:
    sources = []
    started = time.perf_counter()
    tokens = 0
    first_token_at: float | None = None
    log.info("stream_started", question=question[:80], style=style, user=user_id or "-")
    try:
        async for token, srcs in service.stream(
            question, style=style, thread_id=thread_id, user_id=user_id
        ):
            if first_token_at is None:
                # The gap before this is the agent retrieving and calling tools —
                # the window where the UI looks hung. Worth seeing separately from
                # total time, because they have different fixes.
                first_token_at = time.perf_counter() - started
                log.info("stream_first_token", seconds=round(first_token_at, 1))
            tokens += 1
            sources = srcs
            yield {"event": "token", "data": token}
        payload = [Source.from_chunk(c).model_dump() for c in sources]
        yield {"event": "sources", "data": json.dumps(payload)}
        log.info(
            "stream_done",
            tokens=tokens,
            sources=len(payload),
            first_token_s=round(first_token_at or 0, 1),
            total_s=round(time.perf_counter() - started, 1),
        )
    except Exception as exc:  # surface errors to the client instead of hanging
        # Plenty of exceptions carry no message (NotImplementedError being the
        # one that bit us): str() on those is "", so the client got an error
        # event with an empty body and the UI rendered nothing at all. Always
        # send something nameable, and log the traceback server-side — an error
        # nobody can see is indistinguishable from a hang.
        detail = str(exc) or type(exc).__name__
        log.exception("stream_failed", error=detail, kind=type(exc).__name__)
        yield {"event": "error", "data": detail}
    finally:
        yield {"event": "done", "data": "[DONE]"}
