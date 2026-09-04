"""Reload-path regressions: price hydration must not wait for CW analytics."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone

import pytest

from app.market_data.market_snapshot_resolver import MarketSnapshotResolver
from app.quant.quant_engine import LiveQuantEngine
from app.quant.quant_schemas import WarrantAnalytics

pytestmark = pytest.mark.asyncio

_VN = timezone(timedelta(hours=7))
_CLOSED_NOW = datetime(2026, 8, 29, 10, 0, tzinfo=_VN)


async def test_quote_resolution_does_not_invoke_analytics(monkeypatch):
    resolver = MarketSnapshotResolver()

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("quote hydration must not await analytics")

    async def no_bars(*args, **kwargs):
        return []

    monkeypatch.setattr(resolver, "_attach_analytics", fail_if_called)
    monkeypatch.setattr(resolver, "_recent_daily_bars", no_bars)

    rows = await asyncio.wait_for(
        resolver.resolve_rows(["CHPG2602"], now=_CLOSED_NOW), timeout=0.25
    )

    assert len(rows) == 1
    assert rows[0].symbol == "CHPG2602"
    assert rows[0].analytics is None


async def test_many_quote_fallbacks_start_concurrently(monkeypatch):
    resolver = MarketSnapshotResolver()
    symbols = [f"CLOAD{i:02d}" for i in range(30)]
    release = asyncio.Event()
    all_started = asyncio.Event()
    started = 0

    async def gated_bars(*args, **kwargs):
        nonlocal started
        started += 1
        if started == len(symbols):
            all_started.set()
        await release.wait()
        return []

    monkeypatch.setattr(resolver, "_recent_daily_bars", gated_bars)

    task = asyncio.create_task(resolver.resolve_rows(symbols, now=_CLOSED_NOW))
    await asyncio.wait_for(all_started.wait(), timeout=0.25)
    release.set()
    rows = await asyncio.wait_for(task, timeout=0.25)

    assert [row.symbol for row in rows] == symbols


async def test_eod_analytics_singleflight_and_negative_cache(monkeypatch):
    engine = LiveQuantEngine()
    release = asyncio.Event()
    started = asyncio.Event()
    calls = 0
    unavailable = WarrantAnalytics(
        symbol="CHPG2602",
        underlying_symbol="HPG",
        calculated_at="2026-08-28T15:00:00+07:00",
        is_available=False,
        unavailable_reason="EOD_INPUT_MISSING (cw@2026-08-28)",
    )

    async def gated_compute(*args, **kwargs):
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return unavailable

    monkeypatch.setattr(engine, "_compute_eod_analytics_uncached", gated_compute)

    pending = [
        asyncio.create_task(
            engine.compute_eod_analytics("CHPG2602", date(2026, 8, 28))
        )
        for _ in range(3)
    ]
    await asyncio.wait_for(started.wait(), timeout=0.25)
    await asyncio.sleep(0)
    assert calls == 1
    release.set()
    results = await asyncio.gather(*pending)

    assert results == [unavailable, unavailable, unavailable]
    assert calls == 1
    assert await engine.compute_eod_analytics("CHPG2602", date(2026, 8, 28)) == unavailable
    assert calls == 1
