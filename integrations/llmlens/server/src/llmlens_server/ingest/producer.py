"""Enqueue canonical events onto a Redis stream for the worker to consume.
Redis Streams give us a durable, consumer-group-based queue with acks."""

from __future__ import annotations

import json


def enqueue(redis, stream: str, events: list[dict]) -> int:
    if not events:
        return 0
    pipe = redis.pipeline()
    for ev in events:
        pipe.xadd(stream, {"data": json.dumps(ev, default=str)})
    pipe.execute()
    return len(events)
