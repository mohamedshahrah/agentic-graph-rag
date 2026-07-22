"""Redis Stream consumer: read canonical events, enrich with cost, batch-write to
ClickHouse, ack. Runs in the worker process."""

from __future__ import annotations

import json

from llmlens_server.core.logging import get_logger
from llmlens_server.ingest.canonical import event_to_span
from llmlens_server.pricing import PricingTable, compute_cost
from llmlens_server.storage.clickhouse import write_spans

log = get_logger(__name__)


def ensure_group(redis, stream: str, group: str) -> None:
    try:
        redis.xgroup_create(stream, group, id="0", mkstream=True)
    except Exception as exc:
        if "BUSYGROUP" not in str(exc):
            raise


def _process_entries(redis, ch_client, entries, stream, group, pricing: PricingTable, cfg) -> int:
    """Decode, cost-enrich, write, and ack a list of (msg_id, fields) entries."""
    ack_ids: list[str] = []
    spans = []
    for msg_id, fields in entries:
        ack_ids.append(msg_id)
        try:
            span = event_to_span(json.loads(fields["data"]))
            if span.cost_usd == 0.0 and (span.input_tokens or span.output_tokens):
                cost = compute_cost(
                    pricing, span.provider, span.model,
                    span.input_tokens, span.output_tokens,
                )
                if cost is not None:
                    span.cost_usd = cost
            spans.append(span)
        except Exception as exc:  # bad event -> drop + ack (don't block the stream)
            log.warning("bad_event", error=str(exc))

    if spans:
        write_spans(ch_client, spans, record_content=cfg.record_content)
    if ack_ids:
        redis.xack(stream, group, *ack_ids)
    return len(spans)


def consume_once(redis, ch_client, stream, group, consumer, pricing: PricingTable, cfg) -> int:
    resp = redis.xreadgroup(
        group, consumer, {stream: ">"},
        count=cfg.batch_max_events, block=cfg.batch_max_seconds * 1000,
    )
    if not resp:
        return 0
    entries = [entry for _stream, batch in resp for entry in batch]
    return _process_entries(redis, ch_client, entries, stream, group, pricing, cfg)


def claim_stale(
    redis, ch_client, stream, group, consumer, pricing: PricingTable, cfg,
    min_idle_ms: int = 60_000,
) -> int:
    """Recover events a dead consumer read but never acked. Without this, a
    crash between xreadgroup and xack strands those messages forever."""
    try:
        reply = redis.xautoclaim(
            stream, group, consumer, min_idle_time=min_idle_ms, count=cfg.batch_max_events
        )
        entries = reply[1] if isinstance(reply, (list, tuple)) and len(reply) > 1 else []
        if not entries:
            return 0
        n = _process_entries(redis, ch_client, entries, stream, group, pricing, cfg)
        log.info("claimed_stale_events", count=n)
        return n
    except Exception as exc:  # recovery is best-effort; never take down the loop
        log.warning("claim_failed", error=str(exc))
        return 0
