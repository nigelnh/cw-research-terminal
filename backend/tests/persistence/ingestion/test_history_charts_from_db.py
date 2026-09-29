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
async def _closes(symbol: str, price_basis: str) -> dict[str, float]:
    async with session_scope() as s:
        inst = await InstrumentRepository(s).get_by_symbol(symbol)
        rows = await s.execute(
            select(MarketBar.session_date, MarketBar.close).where(
                MarketBar.instrument_id == inst.id, MarketBar.price_basis == price_basis
            )
        )
        return {d.isoformat(): float(c) for d, c in rows.all()}


async def test_the_warm_pass_warms_the_series_the_chart_reads(history_service, fake_provider):
    """A stock chart reads the ADJUSTED series; after the pass it is served with no upstream call."""
    await _seed_instrument("HPG")
    fake_provider.seed_daily("HPG", _CUTOFF - timedelta(days=500), _CUTOFF)

    result = await history_service.warm_universe(["HPG"])
    assert result["stocks_adjusted"]["restated"] == 1
    assert await _bars("HPG", "ADJUSTED") > 0

    fake_provider.calls.clear()
    bars = await history_service.get_history("HPG", timeframe="1D", from_date=None, to_date=None, adjusted=True)
    assert bars and fake_provider.calls == [], "the chart was not served from the warmed table"


async def test_the_restatement_reaches_years_back(history_service, fake_provider):
    """Charts are built from the source's full depth, not the FiinQuant-era 360 days."""
    await _seed_instrument("VNM")
    fake_provider.seed_daily("VNM", _CUTOFF - timedelta(days=3 * 365), _CUTOFF)

    await history_service.warm_universe(["VNM"])
    oldest = min(await _closes("VNM", "ADJUSTED"))
    assert date.fromisoformat(oldest) <= _CUTOFF - timedelta(days=3 * 365 - 7)


async def test_restatement_overwrites_a_series_stored_on_an_old_basis(history_service, fake_provider):
    """After a dividend the source restates every earlier close. A series that keeps the old
    closes beside newly fetched ones shows a step on the ex-date that nobody traded."""
    days = _weekdays(_CUTOFF - timedelta(days=60), _CUTOFF)
    iid = await _seed_instrument("FPT")
    await _insert_bars(iid, days, price_basis="ADJUSTED", base=100.0)   # yesterday's basis
    # The ingestion cursor already claims the range, as it does in production: a plain
    # backfill would skip it as covered, so only a forced re-fetch can restate it.
    await _set_cursor(iid, _CUTOFF - timedelta(days=3700), _CUTOFF, price_basis="ADJUSTED")
    fake_provider.seed_daily("FPT", days[0], _CUTOFF, base=90.0)          # the source, restated

    await history_service.warm_universe(["FPT"])
    stored = await _closes("FPT", "ADJUSTED")
    restated = {iso: b.close for iso, b in fake_provider.bars["FPT"].items()}
    assert stored[days[0].isoformat()] == restated[days[0].isoformat()]
    assert all(stored[d] == restated[d] for d in stored if d in restated)


async def test_a_refused_restatement_keeps_the_stored_series(history_service, fake_provider):
    days = _weekdays(_CUTOFF - timedelta(days=30), _CUTOFF)
    iid = await _seed_instrument("VPB")
    await _insert_bars(iid, days, price_basis="ADJUSTED")
    before = await _closes("VPB", "ADJUSTED")
    fake_provider.fail_symbol["VPB"] = HistoricalTransportError("Failed to fetch data: 400 - Bad Request")

    result = await history_service.warm_universe(["VPB"])
    assert result["stocks_adjusted"] == {"restated": 0, "failed": 1, "bars_written": 0}
    assert await _closes("VPB", "ADJUSTED") == before


async def test_stocks_are_not_warmed_on_raw(history_service, fake_provider):
    """The source has no as-traded history; filling RAW from it wrote restated closes into
    the as-traded series wherever a gap predated the stock's latest corporate action."""
    await _seed_instrument("MWG")
    fake_provider.seed_daily("MWG", _CUTOFF - timedelta(days=200), _CUTOFF)

    await history_service.warm_universe(["MWG"])
    assert await _bars("MWG", "RAW") == 0
    assert all(call[4] is True for call in fake_provider.calls)


async def test_the_warm_pass_registers_symbols_it_has_never_seen(history_service, fake_provider):
    for sym in ("SHB", "CSHB2610"):
        fake_provider.seed_daily(sym, _CUTOFF - timedelta(days=300), _CUTOFF)

    result = await history_service.warm_universe(["SHB", "CSHB2610"])
    assert result["registered"] == 2
    assert result["unresolved"] == 0
    async with session_scope() as s:
        repo = InstrumentRepository(s)
        shb, cw = await repo.get_by_symbol("SHB"), await repo.get_by_symbol("CSHB2610")
    assert shb.instrument_type == "STOCK"
    assert cw.instrument_type == "CW"
    assert await _bars("SHB", "ADJUSTED") > 0
    assert await _bars("CSHB2610", "RAW") > 0


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


async def test_warrants_are_never_warmed_on_an_adjusted_basis(history_service, fake_provider):
    await _seed_instrument("CFPT2614", "CW")
    fake_provider.seed_daily("CFPT2614", _CUTOFF - timedelta(days=200), _CUTOFF, adjusted=False)

    result = await history_service.warm_universe(["CFPT2614"])
    assert result["stocks_adjusted"] == {"restated": 0, "failed": 0, "bars_written": 0}
    assert result["warrants_raw"]["filled"] == 1
    assert all(call[4] is False for call in fake_provider.calls)


async def test_a_full_ten_year_series_is_restated_in_one_go(history_service, fake_provider):
    """Production volume, not a sample. Ten years is ~2,600 daily bars in ONE provider call;
    written as one INSERT that is ~34,000 bind parameters, past Postgres's 32,767. Every
    stock with that much history failed its restatement on 2026-09-29 while the tests,
    seeded with a few hundred bars, passed."""
    await _seed_instrument("VNM")
    start = _CUTOFF - timedelta(days=3690)
    fake_provider.seed_daily("VNM", start, _CUTOFF)

    result = await history_service.warm_universe(["VNM"])
    assert result["stocks_adjusted"]["restated"] == 1, result
    stored = await _closes("VNM", "ADJUSTED")
    assert len(stored) > 2520, "a series longer than one statement's parameter budget"
    assert len(stored) == len(fake_provider.bars["VNM"])
