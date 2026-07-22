"""Send an alert to its channel. Webhook / Slack / log (always safe fallback)."""

from __future__ import annotations

import httpx

from llmlens_server.core.logging import get_logger

log = get_logger(__name__)


def notify(channel: dict | None, message: str) -> None:
    if channel is None or channel.get("kind") == "log":
        log.warning("alert_fired", message=message)
        return
    kind, target = channel.get("kind"), channel.get("target", "")
    try:
        if kind == "slack" and target:
            httpx.post(target, json={"text": f":rotating_light: {message}"}, timeout=5.0)
        elif kind == "webhook" and target:
            httpx.post(target, json={"alert": True, "message": message}, timeout=5.0)
        else:
            log.warning("alert_fired", message=message)
    except Exception as exc:  # never let a bad channel break the alert loop
        log.warning("notify_failed", kind=kind, error=str(exc))
        log.warning("alert_fired", message=message)
