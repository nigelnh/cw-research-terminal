"""Overview hydration is bounded, shared across tabs, and survives worker restart."""

import asyncio
import copy
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.market_data.market_overview_service import MarketOverviewService

pytestmark = pytest.mark.asyncio


def overview(*, settled: bool = True, sparkline_start: str | None = None):
    """A settled payload (the default) mirrors a provider result where the background
    breadth/stock-leaders sweep has already completed - the normal, common case, and what
    every off-session-TTL test other than the one dedicated to the unsettled case wants.
    `top_stock_volume` is left empty either way since only `components` drives the check.

    `sparkline_start`, when given, adds a one-point sparkline to the index starting at that
    ICT timestamp - only the chart-completeness test needs this; every other caller leaves
    it unset so the index carries no sparkline at all (trivially chart-settled)."""
    index = {"symbol": "VNINDEX", "value": 1200, "as_of": "2026-09-03",
             "session_date": "2026-09-03", "stale": False}
    if sparkline_start is not None:
        index["sparkline"] = [{"timestamp": sparkline_start, "value": 1200, "reference": 1190}]
    return {
        "indices": [index],
        "top_stock_volume": [], "top_cw_volume": [], "source": "FIINQUANT",
        "availability": "AVAILABLE", "as_of": "2026-09-03",
        "components": {"top_stock_volume": "AVAILABLE" if settled else "UNAVAILABLE"},
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


async def _settle(service: MarketOverviewService) -> None:
    """Await any refresh `get()` just scheduled, so a following assertion on
    `await_count`/task-identity reflects what actually ran rather than a task that was
    merely created and hasn't had a chance to execute yet."""
    if service._refresh_task is not None:
        await service._refresh_task


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
        await _settle(service)
        assert provider.get_market_overview.await_count == 1

        service._cached_at -= 3600  # an hour passes - the old fixed 300s TTL would refresh
        task_before = service._refresh_task
        await service.get([])
        await _settle(service)
        assert service._refresh_task is task_before  # no new refresh was even scheduled
        assert provider.get_market_overview.await_count == 1  # still cached

        service._seconds_to_next_session = lambda: 10.0  # next session now very close
        await service.get([])
        await _settle(service)
        assert provider.get_market_overview.await_count == 2  # rebuilt
    finally:
        await service.close()


async def test_ttl_stays_short_until_stock_leaders_settle(monkeypatch):
    """A payload built before the background breadth/stock-leaders sweep finished must NOT
    get the long off-session TTL - otherwise "Top Stock Trading Volume" would stay stuck
    empty for the rest of a closed weekend, since nothing would ever re-ask the provider."""
    from app.market_data.market_session import market_session
    monkeypatch.setattr(market_session, "is_trading_active", lambda: False)

    provider = SimpleNamespace(get_market_overview=AsyncMock(side_effect=[
        overview(settled=False), overview(settled=True),
    ]))
    service = MarketOverviewService()
    service.configure(provider, store())
    service._seconds_to_next_session = lambda: 6 * 3600  # e.g. overnight
    try:
        await service.get([])
        await _settle(service)
        assert provider.get_market_overview.await_count == 1

        # A bit over a minute passes - past the short (unsettled) TTL, but nowhere near
        # even the old fixed 300s TTL, let alone the stretched off-session one.
        service._cached_at -= 65
        task_before = service._refresh_task
        await service.get([])
        await _settle(service)
        assert service._refresh_task is not task_before  # retried anyway - it wasn't settled
        assert provider.get_market_overview.await_count == 2

        # Now settled: a later request survives a real multi-hour gap without refetching.
        service._cached_at -= 3600
        task_before = service._refresh_task
        await service.get([])
        await _settle(service)
        assert service._refresh_task is task_before
        assert provider.get_market_overview.await_count == 2
    finally:
        await service.close()


async def test_ttl_stays_short_until_the_chart_covers_the_open(monkeypatch):
    """A payload whose intraday fetch hiccuped and came back starting well after 09:00
    (confirmed live: production served a chart starting ~11:05, missing the whole morning)
    must NOT get the long off-session TTL either - same trap as stock leaders, different
    field, both gated in `_ttl_seconds` via `_sparkline_settled`. Should keep retrying on
    the short TTL until a chart covering the open lands."""
    from app.market_data.market_session import market_session
    monkeypatch.setattr(market_session, "is_trading_active", lambda: False)

    provider = SimpleNamespace(get_market_overview=AsyncMock(side_effect=[
        overview(sparkline_start="2026-09-03T11:05:00+07:00"),
        overview(sparkline_start="2026-09-03T09:00:00+07:00"),
    ]))
    service = MarketOverviewService()
    service.configure(provider, store())
    service._seconds_to_next_session = lambda: 6 * 3600  # e.g. overnight
    try:
        await service.get([])
        await _settle(service)
        assert provider.get_market_overview.await_count == 1

        # A bit over a minute passes - past the short (unsettled) TTL, but nowhere near
        # even the old fixed 300s TTL, let alone the stretched off-session one.
        service._cached_at -= 65
        task_before = service._refresh_task
        await service.get([])
        await _settle(service)
        assert service._refresh_task is not task_before  # retried anyway - it wasn't settled
        assert provider.get_market_overview.await_count == 2

        # Now settled: a later request survives a real multi-hour gap without refetching.
        service._cached_at -= 3600
        task_before = service._refresh_task
        await service.get([])
        await _settle(service)
        assert service._refresh_task is task_before
        assert provider.get_market_overview.await_count == 2
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
