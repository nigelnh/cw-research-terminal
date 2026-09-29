"""Charts are built from PostgreSQL; the upstream fills it, never the viewer's wait.

On 2026-09-29, after the close, every daily chart but one took ~25s to answer: the nightly
warm pass had raised NameError on every tick since it shipped, it warmed ADJUSTED for stocks
while the chart reads RAW, it skipped every symbol with no ``instruments`` row, and an
uncovered chart request held on for the 25s lock wait before being served a partial anyway.

Real disposable PostgreSQL + the deterministic in-memory provider from conftest.
"""

from __future__ import annotations

import asyncio
import time
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.market_data.market_schemas import HistoricalTransportError
from app.persistence.database import session_scope
from app.persistence.models import Instrument, MarketBar
from app.persistence.repositories.instrument_repository import InstrumentRepository

from .test_history_read import _CUTOFF, _insert_bars, _seed_instrument, _set_cursor, _weekdays

pytestmark = pytest.mark.asyncio


async def _bars(symbol: str, price_basis: str) -> int:
    async with session_scope() as s:
        inst = await InstrumentRepository(s).get_by_symbol(symbol)
        if inst is None:
            return 0
        rows = await s.execute(
            select(MarketBar.id).where(
                MarketBar.instrument_id == inst.id, MarketBar.price_basis == price_basis
            )
        )
        return len(rows.all())


# --------------------------------------------------------------------------- #
# The read path answers from PostgreSQL within a bounded wait
# --------------------------------------------------------------------------- #
async def test_a_slow_fill_does_not_hold_the_chart(history_service, fake_provider, monkeypatch):
    monkeypatch.setattr(settings, "HISTORY_REQUEST_FILL_WAIT_SECONDS", 0.2)
    lo = _CUTOFF - timedelta(days=60)
    mid = _CUTOFF - timedelta(days=20)
    iid = await _seed_instrument("HPG")
    await _insert_bars(iid, _weekdays(lo, mid), price_basis="RAW")
    await _set_cursor(iid, lo, mid, price_basis="RAW")
    fake_provider.seed_daily("HPG", lo - timedelta(days=5), _CUTOFF, adjusted=False)
    upstream_answers = asyncio.Event()
    fake_provider.hold["HPG"] = upstream_answers

    started = time.monotonic()
    bars = await history_service.get_history(
        "HPG", timeframe="1D", from_date=lo.isoformat(), to_date=_CUTOFF.isoformat(), adjusted=False,
    )
    assert time.monotonic() - started < 2.0, "the chart waited on the upstream"
    assert bars[-1].date <= mid.isoformat(), "served what PostgreSQL holds, not what it will hold"
    assert history_service._counters["fills_continued_in_background"] == 1  # noqa: SLF001

    # The fill was not abandoned: it completes on its own and the next viewer gets it all.
    fill = history_service._inflight_fills["HPG:1d:RAW"]  # noqa: SLF001
    upstream_answers.set()
    await fill
    calls = len(fake_provider.calls)
    bars2 = await history_service.get_history(
        "HPG", timeframe="1D", from_date=lo.isoformat(), to_date=_CUTOFF.isoformat(), adjusted=False,
    )
    assert bars2[-1].date == _CUTOFF.isoformat()
    assert len(fake_provider.calls) == calls, "a covered range is served without the upstream"


async def test_a_fast_fill_is_still_answered_in_full(history_service, fake_provider):
    """The bounded wait costs nothing when the upstream is quick: same request, full range."""
    lo = _CUTOFF - timedelta(days=60)
    mid = _CUTOFF - timedelta(days=20)
    iid = await _seed_instrument("FPT")
    await _insert_bars(iid, _weekdays(lo, mid), price_basis="RAW")
    await _set_cursor(iid, lo, mid, price_basis="RAW")
    fake_provider.seed_daily("FPT", lo - timedelta(days=5), _CUTOFF, adjusted=False)

    bars = await history_service.get_history(
        "FPT", timeframe="1D", from_date=lo.isoformat(), to_date=_CUTOFF.isoformat(), adjusted=False,
    )
    assert bars[-1].date == _CUTOFF.isoformat()
    assert history_service._counters["fills_continued_in_background"] == 0  # noqa: SLF001


# --------------------------------------------------------------------------- #
# The warm pass fills what the chart reads, for every symbol in the universe
# --------------------------------------------------------------------------- #
async def test_the_warm_pass_warms_the_series_the_chart_reads(history_service, fake_provider):
    """The chart asks for adjusted=false. The pass used to warm only ADJUSTED for stocks."""
    await _seed_instrument("HPG")
    fake_provider.seed_daily("HPG", _CUTOFF - timedelta(days=500), _CUTOFF, adjusted=False)

    result = await history_service.warm_universe(["HPG"])
    assert result["raw"]["filled"] == 1
    assert await _bars("HPG", "RAW") > 0

    fake_provider.calls.clear()
    bars = await history_service.get_history("HPG", timeframe="1D", from_date=None, to_date=None, adjusted=False)
    assert bars and fake_provider.calls == [], "the chart was not served from the warmed table"


async def test_the_warm_pass_registers_symbols_it_has_never_seen(history_service, fake_provider):
    for sym in ("SHB", "CSHB2610"):
        fake_provider.seed_daily(sym, _CUTOFF - timedelta(days=500), _CUTOFF, adjusted=False)

    result = await history_service.warm_universe(["SHB", "CSHB2610"])
    assert result["registered"] == 2
    assert result["unresolved"] == 0
    async with session_scope() as s:
        repo = InstrumentRepository(s)
        shb, cw = await repo.get_by_symbol("SHB"), await repo.get_by_symbol("CSHB2610")
    assert shb.instrument_type == "STOCK"
    assert cw.instrument_type == "CW"
    assert await _bars("SHB", "RAW") > 0 and await _bars("CSHB2610", "RAW") > 0


async def test_registering_never_rewrites_a_seeded_instrument(history_service, fake_provider):
    """`upsert` overwrites every column on conflict. Registration must only touch the absent,
    or it erases the issuer, lifecycle and trading dates the seed wrote."""
    listed, expires = _CUTOFF - timedelta(days=300), _CUTOFF + timedelta(days=90)
    await _seed_instrument("CHPG2618", "CW", first_trade=listed, last_trade=expires)
    fake_provider.seed_daily("CHPG2618", listed, _CUTOFF, adjusted=False)

    result = await history_service.warm_universe(["CHPG2618"])
    assert result["registered"] == 0
    async with session_scope() as s:
        row = (await s.execute(select(Instrument).where(Instrument.symbol == "CHPG2618"))).scalar_one()
    assert (row.first_trade_date, row.last_trade_date) == (listed, expires)


async def test_a_refused_adjusted_series_does_not_cost_the_chart_its_bars(history_service, fake_provider):
    """VCI (ADJUSTED) refusing the host must leave the KBS (RAW) phase whole."""
    await _seed_instrument("VPB")
    fake_provider.seed_daily("VPB", _CUTOFF - timedelta(days=500), _CUTOFF, adjusted=False)
    fake_provider.fail_adjusted["VPB"] = HistoricalTransportError("Failed to fetch data: 400 - Bad Request")

    result = await history_service.warm_universe(["VPB"])
    assert result["raw"] == {"filled": 1, "already_covered": 0, "failed": 0}
    assert result["adjusted"]["failed"] == 1, "a refused fill must be reported as failed, not filled"
    assert await _bars("VPB", "RAW") > 0


async def test_warrants_are_never_warmed_on_an_adjusted_basis(history_service, fake_provider):
    await _seed_instrument("CFPT2614", "CW")
    fake_provider.seed_daily("CFPT2614", _CUTOFF - timedelta(days=200), _CUTOFF, adjusted=False)

    result = await history_service.warm_universe(["CFPT2614"])
    assert result["adjusted"] == {"filled": 0, "already_covered": 0, "failed": 0}
    assert all(call[4] is False for call in fake_provider.calls)
