"""RateLimiter behavior (Step 10 section 25) - deterministic, no real sleeping."""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.security.rate_limiter import RateLimiter, per_minute

pytestmark = pytest.mark.asyncio


async def _fresh(monkeypatch) -> RateLimiter:
    monkeypatch.setattr(settings, "RATE_LIMIT_BACKEND", "memory")
    rl = RateLimiter()
    await rl.configure()
    assert rl.mode == "memory"
    return rl


async def test_allows_burst_then_rejects_excess(monkeypatch):
    rl = await _fresh(monkeypatch)
    items = (per_minute(3),)
    for _ in range(3):
        d = await rl.check(tier="market", key="ip:a", items=items)
        assert d.allowed
    d = await rl.check(tier="market", key="ip:a", items=items)
    assert not d.allowed
    assert d.retry_after >= 1
    assert d.tier == "market"


async def test_different_clients_are_independent(monkeypatch):
    rl = await _fresh(monkeypatch)
    items = (per_minute(2),)
    assert (await rl.check(tier="market", key="ip:a", items=items)).allowed
    assert (await rl.check(tier="market", key="ip:a", items=items)).allowed
    assert not (await rl.check(tier="market", key="ip:a", items=items)).allowed
    # client b is untouched
    assert (await rl.check(tier="market", key="ip:b", items=items)).allowed
    assert (await rl.check(tier="market", key="ip:b", items=items)).allowed


async def test_tiers_do_not_share_a_budget(monkeypatch):
    rl = await _fresh(monkeypatch)
    items = (per_minute(1),)
    assert (await rl.check(tier="market", key="ip:a", items=items)).allowed
    assert not (await rl.check(tier="market", key="ip:a", items=items)).allowed
    assert (await rl.check(tier="quant", key="ip:a", items=items)).allowed  # separate namespace


async def test_reset_clears_the_window(monkeypatch):
    rl = await _fresh(monkeypatch)
    items = (per_minute(1),)
    assert (await rl.check(tier="market", key="ip:a", items=items)).allowed
    assert not (await rl.check(tier="market", key="ip:a", items=items)).allowed
    await rl.reset()
    assert (await rl.check(tier="market", key="ip:a", items=items)).allowed


async def test_multi_window_all_must_pass(monkeypatch):
    rl = await _fresh(monkeypatch)
    from app.security.rate_limiter import per_hour

    items = (per_minute(10), per_hour(2))  # hourly cap is the tighter one
    assert (await rl.check(tier="ai", key="ip:a", items=items)).allowed
    assert (await rl.check(tier="ai", key="ip:a", items=items)).allowed
    d = await rl.check(tier="ai", key="ip:a", items=items)
    assert not d.allowed  # hourly window exhausted even though the minute one isn't


async def test_backend_error_fail_closed_denies(monkeypatch):
    rl = await _fresh(monkeypatch)

    async def boom(*a, **k):
        raise RuntimeError("redis gone")

    monkeypatch.setattr(rl._primary, "hit", boom)
    d = await rl.check(tier="ai", key="ip:a", items=(per_minute(100),), fail_closed=True)
    assert not d.allowed and d.degraded


async def test_backend_error_default_uses_conservative_fallback_not_unlimited(monkeypatch):
    rl = await _fresh(monkeypatch)

    async def boom(*a, **k):
        raise RuntimeError("redis gone")

    monkeypatch.setattr(rl._primary, "hit", boom)
    monkeypatch.setattr(settings, "RATE_LIMIT_FAIL_OPEN", False)
    items = (per_minute(2),)
    assert (await rl.check(tier="market", key="ip:z", items=items)).allowed
    assert (await rl.check(tier="market", key="ip:z", items=items)).allowed
    d = await rl.check(tier="market", key="ip:z", items=items)
    assert not d.allowed and d.degraded  # fallback still enforces a bound


async def test_backend_error_fail_open_allows(monkeypatch):
    rl = await _fresh(monkeypatch)

    async def boom(*a, **k):
        raise RuntimeError("redis gone")

    monkeypatch.setattr(rl._primary, "hit", boom)
    monkeypatch.setattr(settings, "RATE_LIMIT_FAIL_OPEN", True)
    d = await rl.check(tier="market", key="ip:a", items=(per_minute(1),))
    assert d.allowed and d.degraded


async def test_redis_mode_config_validation(monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_BACKEND", "redis")
    monkeypatch.setattr(settings, "RATE_LIMIT_REDIS_URL", "redis://127.0.0.1:1/0")  # unreachable
    monkeypatch.setattr(settings, "REDIS_ENABLED", True)
    rl = RateLimiter()
    await rl.configure()
    # explicitly asked for redis but it is unreachable -> degrades to memory, never crashes
    assert rl.mode == "memory"
    assert rl.health()["backend"] == "memory"
