"""Alert engine: evaluate every enabled rule against ClickHouse, respect a
per-rule cooldown (Redis), and fire notifications + record events."""

from __future__ import annotations

from llmlens_server.alerting import breached, metric_for_rule, notify
from llmlens_server.core.logging import get_logger
from llmlens_server.storage.postgres import repos

log = get_logger(__name__)


def _cooldown_ok(redis, rule: dict) -> bool:
    key = f"alert:cooldown:{rule['id']}"
    # SET NX with TTL: returns True only if the key didn't exist (cooldown elapsed).
    return bool(redis.set(key, "1", nx=True, ex=int(rule["cooldown_seconds"])))


def evaluate_alerts(pg_conn, ch_client, redis) -> int:
    fired = 0
    for rule in repos.list_rules(pg_conn, enabled_only=True):
        try:
            value = metric_for_rule(ch_client, rule)
        except Exception as exc:
            log.warning("alert_eval_failed", rule=rule.get("id"), error=str(exc))
            continue
        if not breached(rule, value):
            continue
        if not _cooldown_ok(redis, rule):
            continue  # already alerted recently
        message = (
            f"[{rule['name']}] {rule['type']} = {value:.4f} "
            f"exceeded threshold {rule['threshold']} "
            f"(window {rule['window_seconds']}s)"
        )
        channel = repos.get_channel(pg_conn, rule["channel_id"]) if rule.get("channel_id") else None
        notify(channel, message)
        repos.insert_alert_event(pg_conn, rule["id"], rule["project_id"], value, message)
        fired += 1
    return fired
