"""Reload-path regressions: price hydration must not wait for CW analytics."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.market_data.market_snapshot_resolver import MarketSnapshotResolver
from app.market_data.market_schemas import HistoricalBar
from app.quant.quant_engine import LiveQuantEngine
from app.quant.quant_schemas import QuantModelInputs, WarrantAnalytics

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


async def test_quote_response_attaches_validated_warm_analytics_without_compute(monkeypatch):
    resolver = MarketSnapshotResolver()
    cached = WarrantAnalytics(
        symbol="CHPG2602",
        underlying_symbol="HPG",
        calculated_at="2026-08-28T14:45:00+07:00",
        session_date="2026-08-28",
        is_available=True,
        is_tradable=True,
        iv_bid=0.35,
        iv_trade=0.36,
        iv_ask=0.37,
        input_provenance={
            "trade": {"asOf": "2026-08-28T14:45:00+07:00"},
            "underlying": {"asOf": "2026-08-28T14:45:00+07:00"},
        },
        model_inputs=QuantModelInputs(
            underlying_price=21_850,
            market_last=570,
            market_bid=560,
            market_ask=580,
        ),
    )

    async def no_bars(*args, **kwargs):
        return []

    def cached_only(symbol, **kwargs):
        assert symbol == "CHPG2602"
        assert kwargs["validate_inputs"] is True
        return cached

    from app.quant.quant_engine import live_quant_engine

    monkeypatch.setattr(resolver, "_recent_daily_bars", no_bars)
    monkeypatch.setattr(live_quant_engine, "get_analytics", cached_only)

    row = (await resolver.resolve_rows(["CHPG2602"], now=_CLOSED_NOW))[0]
    wire = row.to_wire()

    assert wire["analytics"]["ivTrade"] == 0.36
    assert wire["analytics"]["modelInputs"]["market_last"] == 570
    assert wire["provenance"]["analytics"]["source"] == "QUANT_LIVE"
    assert wire["provenance"]["analytics"]["state"] == "SESSION_SNAPSHOT"


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


async def test_fast_reload_returns_observed_snapshot_without_history(monkeypatch):
    resolver = MarketSnapshotResolver()
    snapshot = SimpleNamespace(
        symbol="CHPG2602",
        session_date=date(2026, 8, 28),
        captured_at=datetime(2026, 8, 28, 15, 0, tzinfo=_VN),
        source="SESSION_CLOSE",
        quality="FINAL",
        instrument_type="CW",
        underlying_symbol="HPG",
        reference_price=490.0,
        last_price=440.0,
        total_volume=631_100,
        bid1_price=410.0,
        ask1_price=420.0,
        trade_timestamp=None,
        book_timestamp=None,
    )

    async def snapshots(*args, **kwargs):
        return {"CHPG2602": snapshot}

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("ready snapshot must not wait for daily history")

    monkeypatch.setattr(resolver, "_load_snapshots", snapshots)
    monkeypatch.setattr(resolver, "_recent_daily_bars", fail_if_called)

    row = (
        await resolver.resolve_rows(
            ["CHPG2602"],
            now=_CLOSED_NOW,
            enrich_snapshot_history=False,
        )
    )[0]

    assert row.values["last_price"] == 440.0
    assert row.values["total_volume"] == 631_100
    assert row.values.get("open_price") is None
    assert row.quote_prov.source.value == "SNAPSHOT_FINAL"


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


async def test_history_fallback_reuses_shared_cache_after_resolver_restart(monkeypatch):
    class Store:
        cache = {}

        async def load_dashboard_history(self, symbol, basis, session):
            return self.cache.get((symbol, basis, session))

        async def save_dashboard_history(self, symbol, basis, session, bars):
            self.cache[(symbol, basis, session)] = bars

    store = Store()
    resolver = MarketSnapshotResolver()
    resolver.configure(None, store=store)
    calls = 0

    async def fetch(*args, **kwargs):
        nonlocal calls
        calls += 1
        return [HistoricalBar(
            date="2026-08-28", open=490, high=500, low=430, close=440,
            volume=631100, price_basis="RAW", adjusted=False,
        )]

    monkeypatch.setattr(resolver, "_fetch_recent_daily_bars", fetch)
    first = await resolver._recent_daily_bars("CHPG2602", "CW", now=_CLOSED_NOW)
    assert calls == 1
    assert first[0].price_basis == "RAW"

    restarted = MarketSnapshotResolver()
    restarted.configure(None, store=store)
    monkeypatch.setattr(restarted, "_fetch_recent_daily_bars", fetch)
    second = await restarted._recent_daily_bars("CHPG2602", "CW", now=_CLOSED_NOW)
    assert calls == 1
    assert second == first
