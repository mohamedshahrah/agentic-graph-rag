"""Limit counters and breach reporting.

Redis is faked with a dict so the window arithmetic can be tested without a
server. The database side (effective limits) is covered by the integration
suite, where real global/override rows exist.
"""

from __future__ import annotations

import pytest

from graphrag.limits.service import LimitBreach, Limits, LimitService


class FakeRedis:
    """Enough of the Redis surface for counters and the limits cache."""

    def __init__(self, broken: bool = False) -> None:
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.broken = broken

    def _guard(self):
        if self.broken:
            raise ConnectionError("redis is down")

    def get(self, key):
        self._guard()
        return self.store.get(key)

    def setex(self, key, ttl, value):
        self._guard()
        self.store[key] = value
        self.ttls[key] = ttl

    def delete(self, *keys):
        self._guard()
        for key in keys:
            self.store.pop(key, None)

    def scan_iter(self, match="*", count=100):
        self._guard()
        prefix = match.rstrip("*")
        return [k for k in list(self.store) if k.startswith(prefix)]

    def pipeline(self):
        return _Pipeline(self)


class _Pipeline:
    def __init__(self, redis: FakeRedis) -> None:
        self._redis = redis
        self._ops: list = []

    def incrby(self, key, amount):
        self._ops.append(("incrby", key, amount))
        return self

    def expire(self, key, ttl, nx=False):
        self._ops.append(("expire", key, ttl, nx))
        return self

    def execute(self):
        self._redis._guard()
        for op in self._ops:
            if op[0] == "incrby":
                _, key, amount = op
                self._redis.store[key] = str(int(self._redis.store.get(key, 0)) + amount)
            else:
                _, key, ttl, nx = op
                if not nx or key not in self._redis.ttls:
                    self._redis.ttls[key] = ttl
        self._ops.clear()


LIMITS = Limits(
    messages_per_minute=3, messages_per_day=5,
    tokens_per_day=100, tokens_per_month=1000,
    max_files=2, max_file_mb=5, max_storage_mb=10,
    max_chunks=50, max_threads=4,
)


@pytest.fixture
def service():
    return LimitService(None, FakeRedis())


def test_messages_are_allowed_up_to_the_minute_limit(service):
    for _ in range(LIMITS.messages_per_minute):
        assert service.check_messages("u1", LIMITS) is None
        service.record_message("u1")

    breach = service.check_messages("u1", LIMITS)
    assert breach is not None
    assert breach.limit == "messages_per_minute"
    assert breach.maximum == 3
    assert breach.retry_after > 0


def test_daily_limit_applies_when_it_is_the_tighter_one(service):
    tight = Limits(**{**LIMITS.as_dict(), "messages_per_minute": 100, "messages_per_day": 2})
    for _ in range(2):
        service.record_message("u1")
    breach = service.check_messages("u1", tight)
    assert breach is not None and breach.limit == "messages_per_day"


def test_counters_are_per_user(service):
    for _ in range(LIMITS.messages_per_minute):
        service.record_message("u1")
    assert service.check_messages("u1", LIMITS) is not None
    assert service.check_messages("u2", LIMITS) is None


def test_token_budget_blocks_once_it_is_spent(service):
    assert service.check_tokens("u1", LIMITS) is None
    service.record_tokens("u1", LIMITS.tokens_per_day)

    breach = service.check_tokens("u1", LIMITS)
    assert breach is not None and breach.limit == "tokens_per_day"


def test_partial_token_use_does_not_block(service):
    service.record_tokens("u1", LIMITS.tokens_per_day - 1)
    assert service.check_tokens("u1", LIMITS) is None


async def test_zero_or_negative_tokens_are_ignored(service):
    service.record_tokens("u1", 0)
    service.record_tokens("u1", -5)
    assert (await service.usage_snapshot("u1"))["tokens_today"] == 0


async def test_usage_snapshot_reports_the_counters(service):
    service.record_message("u1")
    service.record_tokens("u1", 42)
    snap = await service.usage_snapshot("u1")
    assert snap["messages_today"] == 1
    assert snap["tokens_today"] == 42
    assert snap["tokens_this_month"] == 42


def test_window_ttl_is_set_once_and_not_extended(service):
    """Refreshing the TTL on every request would keep a busy user's window
    alive forever, so it would never reset."""
    service.record_message("u1")
    key = next(k for k in service._redis.ttls if k.startswith("rl:msg:minute"))
    first = service._redis.ttls[key]
    service._redis.ttls[key] = 1  # pretend time passed
    service.record_message("u1")
    assert service._redis.ttls[key] == 1
    assert first > 1


def test_counters_fail_open_when_redis_is_down():
    """A cache outage must not lock every user out of chat."""
    service = LimitService(None, FakeRedis(broken=True))
    assert service.check_messages("u1", LIMITS) is None
    assert service.check_tokens("u1", LIMITS) is None
    service.record_message("u1")  # must not raise


def test_no_redis_at_all_is_also_permissive():
    service = LimitService(None, None)
    assert service.check_messages("u1", LIMITS) is None


async def test_effective_limits_fall_back_to_defaults_without_a_database():
    limits = await LimitService(None, FakeRedis()).effective("u1")
    assert limits.messages_per_day == 100
    assert limits.max_files == 10
    assert limits.max_chunks == 20_000


async def test_effective_limits_are_cached(service):
    first = await service.effective("u1")
    assert service._cache_get("u1") == first

    service.invalidate("u1")
    assert service._cache_get("u1") is None


async def test_invalidate_without_a_user_clears_everyone(service):
    await service.effective("u1")
    await service.effective("u2")
    service.invalidate()
    assert service._cache_get("u1") is None
    assert service._cache_get("u2") is None


def test_breach_detail_carries_what_the_ui_needs():
    detail = LimitBreach("messages_per_day", 5, 5, 3600).as_detail()
    assert detail["code"] == "limit_exceeded"
    assert detail["limit"] == "messages_per_day"
    assert (detail["used"], detail["max"], detail["retry_after"]) == (5, 5, 3600)
    assert "5" in detail["message"]
