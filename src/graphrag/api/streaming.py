"""Server-Sent Events for streaming answers. The client receives `tool` events
as the agent picks retrieval strategies, incremental `token` events, then one
`sources` event, then `done`."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator

from graphrag.api.schemas import Source
from graphrag.core.logging import get_logger
from graphrag.pipelines import QueryService
from graphrag.usage.recorder import TOKENS_OUT, record_usage

log = get_logger(__name__)


async def sse_message(message: str) -> AsyncIterator[dict]:
    """A complete SSE response that delivers one plain message and no sources.

    Used by the closed-domain gate: the answer is a fixed refusal, so no model is
    called — but the client still gets the token/sources/done shape it expects. No
    `safety` event, because a "not in the knowledge base" refusal is a scope
    decision, not a safety block."""
    yield {"event": "token", "data": message}
    yield {"event": "sources", "data": "[]"}
    yield {"event": "done", "data": "[DONE]"}


async def sse_refusal(message: str) -> AsyncIterator[dict]:
    """A complete SSE response that only delivers a guardrails refusal.

    Used when the input guard blocks a question before the agent ever runs: the
    client still gets the same event shape (a `token`, empty `sources`, `done`)
    plus a leading `safety` event marking why, so no model is called at all."""
    yield {"event": "safety", "data": json.dumps({"action": "block", "stage": "input"})}
    yield {"event": "token", "data": message}
    yield {"event": "sources", "data": "[]"}
    yield {"event": "done", "data": "[DONE]"}


async def sse_answer(
    service: QueryService,
    question: str,
    style: str,
    thread_id: str,
    user_id: str | None = None,
    redis_client=None,
    model=None,
    recorder=None,
    account_id: str | None = None,
    on_complete=None,
    output_guard=None,
) -> AsyncIterator[dict]:
    sources = []
    started = time.perf_counter()
    tokens = 0
    answer_parts: list[str] = []
    first_token_at: float | None = None
    log.info("stream_started", question=question[:80], style=style, user=user_id or "-")
    try:
        async for kind, data, srcs in service.stream(
            question, style=style, thread_id=thread_id, user_id=user_id, model=model
        ):
            sources = srcs
            if kind == "tool":
                # Lets the UI say "searching the graph…" instead of sitting
                # silent through the retrieval phase.
                yield {"event": "tool", "data": data}
                continue
            if first_token_at is None:
                # The gap before this is the agent retrieving and calling tools —
                # the window where the UI looks hung. Worth seeing separately from
                # total time, because they have different fixes.
                first_token_at = time.perf_counter() - started
                log.info("stream_first_token", seconds=round(first_token_at, 1))
            tokens += 1
            answer_parts.append(data)
            yield {"event": "token", "data": data}
        payload = [Source.from_chunk(c).model_dump() for c in sources]
        yield {"event": "sources", "data": json.dumps(payload)}

        # Output guard (monitor mode on the stream): the tokens have already
        # reached the client, so a streamed answer can't be rewritten or held
        # back — instead we surface the verdict as a `safety` event the UI can
        # act on. The non-streaming path enforces (block/redact) fully.
        if output_guard is not None:
            try:
                verdict = await output_guard("".join(answer_parts), sources)
            except Exception as exc:  # a safety add-on must never break the answer
                log.warning("stream_output_guard_failed", error=str(exc) or type(exc).__name__)
                verdict = None
            if verdict is not None and (verdict.blocked or verdict.flagged or verdict.modified):
                yield {
                    "event": "safety",
                    "data": json.dumps(
                        {
                            "action": verdict.action,
                            "stage": "output",
                            "reasons": verdict.reasons,
                            "modified": verdict.modified,
                        }
                    ),
                }

        record_usage(redis_client, user_id, tokens)
        if recorder is not None and account_id:
            await recorder.record(account_id, TOKENS_OUT, tokens, {"style": style})
        if on_complete is not None:
            # After `sources`, so a slow write cannot delay the visible answer.
            await on_complete("".join(answer_parts), sources)

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
