"""Worker process: one sync loop that consumes the ingest stream and, on an
interval, evaluates alert rules. Kept single-threaded and simple — it can be
scaled horizontally (each replica joins the same consumer group)."""

from __future__ import annotations

import os
import socket
import time

from llmlens_server.config import load_settings
from llmlens_server.core.logging import configure_logging, get_logger
from llmlens_server.pricing import PricingTable
from llmlens_server.redis_client import get_redis
from llmlens_server.storage import postgres, setup_storage
from llmlens_server.storage.clickhouse import get_client
from llmlens_server.worker.alerts import evaluate_alerts
from llmlens_server.worker.consumer import claim_stale, consume_once, ensure_group

_CLAIM_INTERVAL_S = 60.0


def _load_pricing(secrets) -> PricingTable:
    try:
        with postgres.connect(secrets.postgres_dsn) as conn:
            return PricingTable.from_rows(postgres.repos.load_pricing(conn))
    except Exception:
        return PricingTable.from_seed()


def _wait_for_storage(settings, secrets, log):
    """Block until ClickHouse/Postgres/Redis are reachable and schemas exist.
    The worker has no HTTP surface, so retrying beats crash-looping."""
    while True:
        try:
            setup_storage(settings, secrets)
            redis = get_redis(secrets.redis_url)
            ch = get_client(secrets)
            ensure_group(redis, settings.ingest.queue_stream, settings.ingest.consumer_group)
            return redis, ch
        except Exception as exc:
            log.warning("storage_not_ready", error=str(exc))
            time.sleep(3.0)


def run() -> None:
    settings, secrets = load_settings()
    configure_logging(settings.app.log_level)
    log = get_logger("worker")

    redis, ch = _wait_for_storage(settings, secrets, log)
    stream, group = settings.ingest.queue_stream, settings.ingest.consumer_group
    consumer = f"{socket.gethostname()}-{os.getpid()}"
    pricing = _load_pricing(secrets)

    last_alert = 0.0
    last_pricing = time.time()
    last_claim = 0.0
    log.info("worker_ready", stream=stream, consumer=consumer)

    while True:
        try:
            consume_once(redis, ch, stream, group, consumer, pricing, settings.ingest)
        except Exception as exc:
            log.warning("consume_error", error=str(exc))
            time.sleep(1.0)

        now = time.time()
        if now - last_claim >= _CLAIM_INTERVAL_S:
            claim_stale(redis, ch, stream, group, consumer, pricing, settings.ingest)
            last_claim = now

        if settings.alerting.enabled and now - last_alert >= settings.alerting.interval_seconds:
            try:
                with postgres.connect(secrets.postgres_dsn) as conn:
                    fired = evaluate_alerts(conn, ch, redis)
                if fired:
                    log.info("alerts_fired", count=fired)
            except Exception as exc:
                log.warning("alert_loop_error", error=str(exc))
            last_alert = now

        if now - last_pricing >= 300:
            pricing = _load_pricing(secrets)
            last_pricing = now
