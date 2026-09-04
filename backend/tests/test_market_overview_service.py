"""Overview hydration is bounded, shared across tabs, and survives worker restart."""

import asyncio
import copy
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.market_data.market_overview_service import MarketOverviewService

pytestmark = pytest.mark.asyncio


def overview():
    return {
        "indices": [{"symbol": "VNINDEX", "value": 1200, "as_of": "2026-09-03",
                     "session_date": "2026-09-03", "stale": False}],
        "top_stock_volume": [], "top_cw_volume": [], "source": "FIINQUANT",
        "availability": "AVAILABLE", "as_of": "2026-09-03",
    }


def store(saved=None):
    return SimpleNamespace(load_market_overview=AsyncMock(return_value=saved),
                           save_market_overview=AsyncMock())


async def test_two_cold_tabs_share_refresh_and_do_not_cancel_it_on_timeout():
    gate = asyncio.Event()

    async def slow(symbols):
        await gate.wait()
        return overview()

    provider = SimpleNamespace(get_market_overview=AsyncMock(side_effect=slow))
    cache = store()
    service = MarketOverviewService(cold_read_timeout=0.01)
    service.configure(provider, cache)
    try:
        results = await asyncio.wait_for(asyncio.gather(service.get([]), service.get([])), 0.5)
        assert all(r["availability"] == "UNAVAILABLE" and r["refreshing"] for r in results)
        assert provider.get_market_overview.await_count == 1
        assert not service._refresh_task.cancelled()
        gate.set()
        await service._refresh_task
        assert (await service.get([]))["indices"][0]["value"] == 1200
        cache.save_market_overview.assert_awaited_once()
    finally:
        await service.close()


async def test_restart_restores_stale_snapshot_without_waiting_for_provider():
    original = overview()
    saved = {"payload": original, "cached_at": time.time() - 3600}
    provider = SimpleNamespace(get_market_overview=AsyncMock(side_effect=lambda _: None))
    gate = asyncio.Event()

    async def slow(symbols):
        await gate.wait()
        return overview()

    provider.get_market_overview.side_effect = slow
    service = MarketOverviewService()
    service.configure(provider, store(saved))
    # Off-session the TTL stretches to the next real session open; pin it small so a
    # 1-hour-old cache is deterministically stale regardless of when this test runs.
    service._seconds_to_next_session = lambda: 1.0
    try:
        result = await asyncio.wait_for(service.get([]), 0.1)
        assert result["indices"][0]["value"] == 1200
        assert result["indices"][0]["stale"] is True
        assert result["indices"][0]["session_date"] == "2026-09-03"
        assert result["as_of"] == "2026-09-03"
        assert result["source"] == "FIINQUANT_CACHE"
        assert result["refreshing"] is True
        assert result["cache_age_seconds"] >= 3600
        assert original == overview()  # adding stale metadata never mutates stored observations
    finally:
        await service.close()


async def test_fresh_redis_snapshot_does_not_call_provider():
    provider = SimpleNamespace(get_market_overview=AsyncMock())
    service = MarketOverviewService()
    service.configure(provider, store({"payload": overview(), "cached_at": time.time()}))
    result = await service.get([])
    assert result["indices"][0]["value"] == 1200
    assert result["refreshing"] is False
    provider.get_market_overview.assert_not_called()


async def test_unavailable_refresh_preserves_last_good_snapshot():
    provider = SimpleNamespace(get_market_overview=AsyncMock(return_value={"indices": []}))
    cache = store({"payload": overview(), "cached_at": time.time() - 3600})
    service = MarketOverviewService()
    service.configure(provider, cache)
    service._seconds_to_next_session = lambda: 1.0  # deterministic off-session TTL
    await service.get([])
    await service._refresh_task
    result = await service.get([])
    assert result["indices"][0]["value"] == 1200
    assert result["stale"] is True
    assert result["refreshing"] is False
    assert provider.get_market_overview.await_count == 1
    cache.save_market_overview.assert_not_called()


async def test_ttl_extends_through_the_closed_stretch_but_not_past_the_next_session(monkeypatch):
    """Outside trading hours nothing can change until the market reopens, so a request an
    hour after the last fetch must still be served from cache - but not forever: once the
    next session is genuinely close, the cache still rebuilds."""
    from app.market_data.market_session import market_session
    monkeypatch.setattr(market_session, "is_trading_active", lambda: False)

    provider = SimpleNamespace(get_market_overview=AsyncMock(return_value=overview()))
    service = MarketOverviewService()
    service.configure(provider, store())
    service._seconds_to_next_session = lambda: 6 * 3600  # e.g. overnight
    try:
        await service.get([])
        await service._refresh_task
        assert provider.get_market_overview.await_count == 1

        service._cached_at -= 3600  # an hour passes - the old fixed 300s TTL would refresh
        await service.get([])
        assert provider.get_market_overview.await_count == 1  # still cached

        service._seconds_to_next_session = lambda: 10.0  # next session now very close
        await service.get([])
        await service._refresh_task
        assert provider.get_market_overview.await_count == 2  # rebuilt
    finally:
        await service.close()


async def test_failed_refresh_is_bounded_and_backed_off():
    provider = SimpleNamespace(get_market_overview=AsyncMock(side_effect=RuntimeError("offline")))
    service = MarketOverviewService()
    service.configure(provider, store())
    assert (await service.get([]))["availability"] == "UNAVAILABLE"
    assert (await service.get([]))["availability"] == "UNAVAILABLE"
    assert provider.get_market_overview.await_count == 1


@pytest.mark.parametrize("saved", [
    {"payload": overview(), "cached_at": "invalid"},
    {"payload": {"indices": None}, "cached_at": time.time()},
])
async def test_malformed_cache_does_not_prevent_recovery(saved):
    provider = SimpleNamespace(get_market_overview=AsyncMock(return_value=overview()))
    service = MarketOverviewService()
    service.configure(provider, store(copy.deepcopy(saved)))
    assert (await service.get([]))["indices"][0]["value"] == 1200
    provider.get_market_overview.assert_awaited_once()
