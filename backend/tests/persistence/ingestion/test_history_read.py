"""Step 7 - PostgreSQL-first `/api/market/history` read path.

Real disposable PostgreSQL + a deterministic in-memory provider. Proves:
DB hit -> zero provider calls; partial coverage -> one controlled fill; out-of-horizon ->
zero provider calls; CW adjusted=true -> RAW; concurrency -> one fill lifecycle;
provider failure -> DB rows preserved.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone

import pytest

from app.core.config import settings
from app.market_data.market_schemas import (
    HistoricalRateLimitError,
    HistoricalTransportError,
)
from app.persistence.database import session_scope
from app.persistence.ingestion.trading_calendar import last_completed_session_date
from app.persistence.market_time import VN_TZ
from app.persistence.models import MarketBar
from app.persistence.repositories.instrument_repository import InstrumentRepository, InstrumentUpsert
from app.persistence.repositories.market_bar_repository import MarketBarRepository
from app.persistence.rows import BarUpsert
from sqlalchemy import func, select

pytestmark = pytest.mark.asyncio

_CUTOFF = last_completed_session_date()


async def _seed_instrument(symbol: str, itype: str = "STOCK", *, first_trade=None, last_trade=None) -> int:
    async with session_scope() as s:
        row = await InstrumentRepository(s).upsert(
            InstrumentUpsert(symbol=symbol, instrument_type=itype,
                             first_trade_date=first_trade, last_trade_date=last_trade)
        )
    return row.id


async def _insert_bars(instrument_id: int, days: list[date], *, price_basis="ADJUSTED", base=100.0):
    rows = [
        BarUpsert(
            instrument_id=instrument_id, timeframe="1d",
            ts=datetime(d.year, d.month, d.day, tzinfo=VN_TZ).astimezone(timezone.utc),
            open=base + i, high=base + i + 1, low=base + i - 1, close=base + i + 0.5,
            volume=1000 + i, price_basis=price_basis, source="fiinquant", session_date=d,
        )
        for i, d in enumerate(days)
    ]
    async with session_scope() as s:
        await MarketBarRepository(s).bulk_upsert_bars(rows)


async def _set_cursor(instrument_id: int, lo: date, hi: date, price_basis="ADJUSTED"):
    from app.persistence.repositories.ingestion_repository import IngestionRepository

    async with session_scope() as s:
        await IngestionRepository(s).upsert_state(
            source="fiinquant", instrument_id=instrument_id, timeframe="1d", price_basis=price_basis,
            backfilled_from_ts=datetime(lo.year, lo.month, lo.day, tzinfo=VN_TZ).astimezone(timezone.utc),
            last_bar_ts=datetime(hi.year, hi.month, hi.day, tzinfo=VN_TZ).astimezone(timezone.utc),
            last_success_at=datetime.now(timezone.utc),
        )


def _weekdays(lo: date, hi: date) -> list[date]:
    return [lo + timedelta(days=i) for i in range((hi - lo).days + 1) if (lo + timedelta(days=i)).weekday() < 5]


# --------------------------------------------------------------------------- #
# 15 - DB HIT
# --------------------------------------------------------------------------- #
async def test_full_coverage_returns_bars_with_zero_provider_calls(history_service, fake_provider):
    lo, hi = _CUTOFF - timedelta(days=40), _CUTOFF
    iid = await _seed_instrument("HPG")
    days = _weekdays(lo, hi)
    await _insert_bars(iid, days)
    await _set_cursor(iid, lo, hi)

    bars = await history_service.get_history("HPG", timeframe="1D", from_date=lo.isoformat(), to_date=hi.isoformat(), adjusted=True)

    assert [b.date for b in bars] == [d.isoformat() for d in days]     # correct order + boundaries
    assert all(b.adjusted for b in bars)
    assert fake_provider.calls == []                                    # ZERO provider calls
    assert history_service.health()["counters"]["db_hit_reads"] == 1


async def test_adjusted_reads_adjusted_and_raw_reads_raw(history_service, fake_provider):
    lo, hi = _CUTOFF - timedelta(days=20), _CUTOFF
    iid = await _seed_instrument("HPG")
    days = _weekdays(lo, hi)
    await _insert_bars(iid, days, price_basis="ADJUSTED", base=100.0)
    await _insert_bars(iid, days, price_basis="RAW", base=200.0)
    await _set_cursor(iid, lo, hi, "ADJUSTED")
    await _set_cursor(iid, lo, hi, "RAW")

    adj = await history_service.get_history("HPG", timeframe="1D", from_date=lo.isoformat(), to_date=hi.isoformat(), adjusted=True)
    raw = await history_service.get_history("HPG", timeframe="1D", from_date=lo.isoformat(), to_date=hi.isoformat(), adjusted=False)
    assert adj[0].close < 150 and raw[0].close > 150
    assert adj[0].adjusted is True and raw[0].adjusted is False
    assert fake_provider.calls == []


async def test_cw_adjusted_true_transparently_reads_raw(history_service, fake_provider):
    lo, hi = _CUTOFF - timedelta(days=20), _CUTOFF
    iid = await _seed_instrument("CHPG2612", "CW")
    days = _weekdays(lo, hi)
    await _insert_bars(iid, days, price_basis="RAW", base=3.5)
    await _set_cursor(iid, lo, hi, "RAW")

    # frontend always sends adjusted=true for CWs; must resolve to the persisted RAW series
    bars = await history_service.get_history("CHPG2612", timeframe="1D", from_date=lo.isoformat(), to_date=hi.isoformat(), adjusted=True)
    assert len(bars) == len(days)
    assert all(b.adjusted is False for b in bars)                       # not falsely labelled ADJUSTED
    assert fake_provider.calls == []


async def test_wire_shape_is_unchanged(history_service):
    lo, hi = _CUTOFF - timedelta(days=10), _CUTOFF
    iid = await _seed_instrument("HPG")
    await _insert_bars(iid, _weekdays(lo, hi))
    await _set_cursor(iid, lo, hi)
    bars = await history_service.get_history("HPG", timeframe="1D", from_date=lo.isoformat(), to_date=hi.isoformat(), adjusted=True)
    b = bars[0].model_dump()
    assert set(b) == {"as_of", "complete", "date", "open", "high", "low", "close", "volume", "value",
                      "adjusted", "price_basis", "source", "session_date"}
    assert isinstance(b["date"], str) and isinstance(b["close"], float)


# --------------------------------------------------------------------------- #
# 16 - PARTIAL COVERAGE
# --------------------------------------------------------------------------- #
async def test_A_missing_tail_triggers_one_fill_then_complete(history_service, fake_provider):
    """DB covers [lo, mid]; provider has [lo, cutoff]. Read [lo, cutoff] -> one fill of the tail."""
    lo = _CUTOFF - timedelta(days=60)
    mid = _CUTOFF - timedelta(days=20)
    iid = await _seed_instrument("HPG")
    await _insert_bars(iid, _weekdays(lo, mid))
    await _set_cursor(iid, lo, mid)
    fake_provider.seed_daily("HPG", lo - timedelta(days=5), _CUTOFF)

    bars = await history_service.get_history("HPG", timeframe="1D", from_date=lo.isoformat(), to_date=_CUTOFF.isoformat(), adjusted=True)
    assert len(fake_provider.calls) == 1                                # exactly one controlled fill
    assert [b.date for b in bars][-1] == _CUTOFF.isoformat()            # tail now present
    async with session_scope() as s:
        n = (await s.execute(select(func.count()).select_from(MarketBar).where(MarketBar.instrument_id == iid))).scalar_one()
    assert n == len(_weekdays(lo, _CUTOFF))

    # second identical request: zero provider calls
    fake_provider.calls.clear()
    bars2 = await history_service.get_history("HPG", timeframe="1D", from_date=lo.isoformat(), to_date=_CUTOFF.isoformat(), adjusted=True)
    assert fake_provider.calls == []
    assert len(bars2) == len(bars)


async def test_B_missing_middle_gap_filled_without_touching_surrounding(history_service, fake_provider):
    lo = _CUTOFF - timedelta(days=60)
    hi = _CUTOFF - timedelta(days=5)
    gap_lo = _CUTOFF - timedelta(days=35)
    gap_hi = _CUTOFF - timedelta(days=30)
    iid = await _seed_instrument("HPG")
    present = [d for d in _weekdays(lo, hi) if not (gap_lo <= d <= gap_hi)]
    await _insert_bars(iid, present, base=500.0)
    # cursor only spans the first segment -> the middle is genuinely un-probed
    await _set_cursor(iid, lo, gap_lo - timedelta(days=1))
    fake_provider.seed_daily("HPG", lo - timedelta(days=5), hi, base=777.0)

    async with session_scope() as s:
        rows_before = await MarketBarRepository(s).get_bars(instrument_id=iid, timeframe="1d", price_basis="ADJUSTED")
    surviving_closes = {r.session_date: float(r.close) for r in rows_before}

    bars = await history_service.get_history("HPG", timeframe="1D", from_date=lo.isoformat(), to_date=hi.isoformat(), adjusted=True)
    dates = {b.date for b in bars}
    for d in _weekdays(gap_lo, gap_hi):
        assert d.isoformat() in dates                                   # gap filled
    # surrounding rows preserved unchanged (still base 500, not overwritten with 777)
    async with session_scope() as s:
        rows_after = await MarketBarRepository(s).get_bars(instrument_id=iid, timeframe="1d", price_basis="ADJUSTED")
    for r in rows_after:
        if r.session_date in surviving_closes:
            assert float(r.close) == surviving_closes[r.session_date]


async def test_probed_but_missing_day_retries_only_within_the_recent_window(history_service, fake_provider):
    """A prior fill's `requested_ceiling` (ingestion/service.py._run_chunks) stamps the
    cursor through the day it asked for even when the provider had nothing for it yet -
    FiinQuant routinely publishes a session's final daily bar hours after close (confirmed
    live: the ADJUSTED series lagged RAW by more than a day for some tickers). Without an
    age-based override, that day is "probed" forever and a chart/quant read never retries
    it even once the provider actually has it. `HISTORY_RECENT_RETRY_DAYS` bounds the
    override so it only applies close to today - an old gap this far back must stay a
    zero-provider-call, cursor-trusted read, or every load would re-hammer a confirmed
    historical hole forever."""
    lo = _CUTOFF - timedelta(days=90)
    all_days = _weekdays(lo, _CUTOFF)
    recent_gap = all_days[-2]                                  # a few calendar days back, always inside the window
    old_gap = _CUTOFF - timedelta(days=settings.HISTORY_RECENT_RETRY_DAYS + 20)
    while old_gap.weekday() >= 5:                               # snap onto a real weekday
        old_gap -= timedelta(days=1)

    # --- Recent gap: cursor already claims full coverage through cutoff (as if an earlier
    # fill's requested_ceiling raced the publish lag), but recent_gap's bar was never
    # actually written. The provider has it NOW - must retry and pick it up.
    recent_iid = await _seed_instrument("HPG")
    await _insert_bars(recent_iid, [d for d in all_days if d != recent_gap])
    await _set_cursor(recent_iid, lo, _CUTOFF)
    fake_provider.seed_daily("HPG", lo - timedelta(days=5), _CUTOFF)

    bars = await history_service.get_history(
        "HPG", timeframe="1D", from_date=lo.isoformat(), to_date=_CUTOFF.isoformat(), adjusted=True,
    )
    assert len(fake_provider.calls) == 1
    assert recent_gap.isoformat() in [b.date for b in bars]

    # --- Old gap, same shape, different symbol: this far back, the cursor is trusted -
    # zero provider calls, the historical hole stays a hole (unchanged pre-fix behavior).
    fake_provider.calls.clear()
    old_iid = await _seed_instrument("FPT")
    await _insert_bars(old_iid, [d for d in all_days if d != old_gap])
    await _set_cursor(old_iid, lo, _CUTOFF)
    fake_provider.seed_daily("FPT", lo - timedelta(days=5), _CUTOFF)

    bars2 = await history_service.get_history(
        "FPT", timeframe="1D", from_date=lo.isoformat(), to_date=_CUTOFF.isoformat(), adjusted=True,
    )
    assert fake_provider.calls == []
    assert old_gap.isoformat() not in [b.date for b in bars2]


async def test_C_old_range_outside_entitlement_makes_zero_provider_calls(history_service, fake_provider):
    iid = await _seed_instrument("HPG")
    await _insert_bars(iid, _weekdays(_CUTOFF - timedelta(days=20), _CUTOFF))
    # request a range ~2 years old, absent from DB and outside the ~360d provider horizon
    old_from = date.today() - timedelta(days=720)
    old_to = date.today() - timedelta(days=600)
    fake_provider.seed_daily("HPG", old_from, old_to)                   # provider *would* have it, but must not be asked

    bars = await history_service.get_history("HPG", timeframe="1D", from_date=old_from.isoformat(), to_date=old_to.isoformat(), adjusted=True)
    assert bars == []
    assert fake_provider.calls == []
    assert history_service.health()["counters"]["gap_fills_attempted"] == 0


async def test_D_instrument_listed_after_requested_start_is_not_a_gap(history_service, fake_provider):
    listing = _CUTOFF - timedelta(days=30)
    iid = await _seed_instrument("NEWCO", first_trade=listing)
    days = _weekdays(listing, _CUTOFF)
    await _insert_bars(iid, days)
    await _set_cursor(iid, listing, _CUTOFF)
    fake_provider.seed_daily("NEWCO", listing - timedelta(days=90), _CUTOFF)

    # request starts 90 days before listing; the pre-listing absence must NOT trigger a fill
    bars = await history_service.get_history(
        "NEWCO", timeframe="1D", from_date=(listing - timedelta(days=90)).isoformat(), to_date=_CUTOFF.isoformat(), adjusted=True
    )
    assert fake_provider.calls == []
    assert [b.date for b in bars] == [d.isoformat() for d in days]


async def test_E_expired_cw_after_last_trading_date_is_not_filled(history_service, fake_provider):
    delist = _CUTOFF - timedelta(days=15)
    iid = await _seed_instrument("CEXP2601", "CW", last_trade=delist)
    days = _weekdays(_CUTOFF - timedelta(days=60), delist)
    await _insert_bars(iid, days, price_basis="RAW")
    await _set_cursor(iid, days[0], delist, "RAW")
    fake_provider.seed_daily("CEXP2601", _CUTOFF - timedelta(days=60), _CUTOFF, adjusted=False)

    bars = await history_service.get_history(
        "CEXP2601", timeframe="1D", from_date=(_CUTOFF - timedelta(days=60)).isoformat(), to_date=_CUTOFF.isoformat(), adjusted=True
    )
    assert fake_provider.calls == []                                    # no fill past the CW's trading life
    # The last SEEDED session, not `delist` itself: the bars are weekdays, so whenever the
    # delisting date happens to fall on a weekend the final bar is the Friday before it.
    # Asserting on `delist` made this pass or fail according to the day of the week.
    assert [b.date for b in bars][-1] == days[-1].isoformat()


# --------------------------------------------------------------------------- #
# 17 - CONCURRENCY
# --------------------------------------------------------------------------- #
async def test_20_concurrent_cache_misses_produce_one_fill_lifecycle(history_service, fake_provider):
    lo = _CUTOFF - timedelta(days=50)
    mid = _CUTOFF - timedelta(days=25)
    iid = await _seed_instrument("HPG")
    await _insert_bars(iid, _weekdays(lo, mid))
    await _set_cursor(iid, lo, mid)
    fake_provider.seed_daily("HPG", lo - timedelta(days=5), _CUTOFF)

    results = await asyncio.gather(*(
        history_service.get_history("HPG", timeframe="1D", from_date=lo.isoformat(), to_date=_CUTOFF.isoformat(), adjusted=True)
        for _ in range(20)
    ))
    # exactly ONE provider fill lifecycle despite 20 simultaneous misses
    assert len(fake_provider.calls) == 1
    lengths = {len(r) for r in results}
    assert len(lengths) == 1                                            # all 20 return the same complete series
    assert list(results[0])[-1].date == _CUTOFF.isoformat()


async def test_global_gapfill_concurrency_cap_serves_db_partial(history_service, fake_provider, monkeypatch):
    """Step 10: an HTTP-layer cap on how many DISTINCT streams may trigger a provider fill
    at once. With the cap at 1 and a slow provider, a second distinct-symbol miss serves
    the DB partial instead of starting a second upstream call."""
    import asyncio

    from app.core.config import settings as app_settings
    from app.security.concurrency import history_gapfill_gate

    monkeypatch.setattr(app_settings, "HISTORY_MAX_CONCURRENT_GAPFILLS", 1)
    monkeypatch.setattr(app_settings, "HISTORY_GAPFILL_LOCK_WAIT_SECONDS", 0.1)
    history_gapfill_gate.set_limit(1)

    lo = _CUTOFF - timedelta(days=40)
    mid = _CUTOFF - timedelta(days=20)
    ids = {}
    for sym in ("HPG", "VHM"):
        ids[sym] = await _seed_instrument(sym)
        await _insert_bars(ids[sym], _weekdays(lo, mid))
        await _set_cursor(ids[sym], lo, mid)
        fake_provider.seed_daily(sym, lo - timedelta(days=5), _CUTOFF)

    _orig = fake_provider.get_historical_bars

    async def _slow(*a, **k):
        await asyncio.sleep(0.3)
        return await _orig(*a, **k)

    monkeypatch.setattr(fake_provider, "get_historical_bars", _slow)

    results = await asyncio.gather(*(
        history_service.get_history(sym, timeframe="1D", from_date=lo.isoformat(),
                                    to_date=_CUTOFF.isoformat(), adjusted=True)
        for sym in ("HPG", "VHM")
    ))
    # one fill got the slot; the other was deferred -> its result is the (shorter) DB partial
    lengths = sorted(len(r) for r in results)
    assert lengths[0] < lengths[1]
    assert history_service._counters["gap_fills_rejected_saturated"] >= 1
    history_gapfill_gate.set_limit(app_settings.HISTORY_MAX_CONCURRENT_GAPFILLS)


async def test_different_symbols_fill_independently(history_service, fake_provider):
    lo = _CUTOFF - timedelta(days=40)
    mid = _CUTOFF - timedelta(days=20)
    ids = {}
    for sym in ("HPG", "VHM"):
        ids[sym] = await _seed_instrument(sym)
        await _insert_bars(ids[sym], _weekdays(lo, mid))
        await _set_cursor(ids[sym], lo, mid)
        fake_provider.seed_daily(sym, lo - timedelta(days=5), _CUTOFF)

    await asyncio.gather(*(
        history_service.get_history(sym, timeframe="1D", from_date=lo.isoformat(), to_date=_CUTOFF.isoformat(), adjusted=True)
        for sym in ("HPG", "VHM", "HPG", "VHM")
    ))
    called = sorted({c[0] for c in fake_provider.calls})
    assert called == ["HPG", "VHM"]
    assert len(fake_provider.calls) == 2                                # one per symbol


async def test_provider_failure_while_lock_held_lets_waiters_recover(history_service, fake_provider):
    lo = _CUTOFF - timedelta(days=40)
    mid = _CUTOFF - timedelta(days=20)
    iid = await _seed_instrument("HPG")
    await _insert_bars(iid, _weekdays(lo, mid))
    await _set_cursor(iid, lo, mid)
    # first fill attempt fails; the fake has no bars so nothing new persists either
    fake_provider.fail_symbol["HPG"] = HistoricalTransportError("net down")

    results = await asyncio.gather(*(
        history_service.get_history("HPG", timeframe="1D", from_date=lo.isoformat(), to_date=_CUTOFF.isoformat(), adjusted=True)
        for _ in range(8)
    ), return_exceptions=True)
    # no deadlock, no exception surfaced to callers; every caller got the surviving DB rows
    assert all(not isinstance(r, BaseException) for r in results)
    for r in results:
        assert not isinstance(r, BaseException) and len(r) == len(_weekdays(lo, mid))
    async with session_scope() as s:
        n = (await s.execute(select(func.count()).select_from(MarketBar).where(MarketBar.instrument_id == iid))).scalar_one()
    assert n == len(_weekdays(lo, mid))                                 # existing rows preserved


# --------------------------------------------------------------------------- #
# 18 - FAILURE DEGRADATION
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("exc", [
    HistoricalTransportError("drop"),
    HistoricalRateLimitError("429"),
])
async def test_partial_db_data_survives_provider_failure(history_service, fake_provider, exc):
    lo = _CUTOFF - timedelta(days=40)
    mid = _CUTOFF - timedelta(days=15)
    iid = await _seed_instrument("HPG")
    await _insert_bars(iid, _weekdays(lo, mid), base=321.0)
    await _set_cursor(iid, lo, mid)
    fake_provider.fail_symbol["HPG"] = exc

    bars = await history_service.get_history("HPG", timeframe="1D", from_date=lo.isoformat(), to_date=_CUTOFF.isoformat(), adjusted=True)
    assert len(bars) == len(_weekdays(lo, mid))                         # stale/partial DB preferred over zero rows
    assert all(abs(b.close - 321.0) < 60 for b in bars)                 # original rows, not deleted / overwritten

    # a failed fill sets a cooldown -> the next request does NOT hammer the provider
    fake_provider.calls.clear()
    await history_service.get_history("HPG", timeframe="1D", from_date=lo.isoformat(), to_date=_CUTOFF.isoformat(), adjusted=True)
    assert fake_provider.calls == []
    assert history_service.health()["counters"]["gap_fills_suppressed_cooldown"] >= 1


async def test_no_generic_500_and_no_infinite_retry_on_typed_failure(history_service, fake_provider):
    lo = _CUTOFF - timedelta(days=30)
    mid = _CUTOFF - timedelta(days=10)
    iid = await _seed_instrument("HPG")
    await _insert_bars(iid, _weekdays(lo, mid))
    await _set_cursor(iid, lo, mid)
    fake_provider.fail_symbol["HPG"] = HistoricalTransportError("boom")

    # get_history never raises for a typed provider failure when DB has usable data
    bars = await history_service.get_history("HPG", timeframe="1D", from_date=lo.isoformat(), to_date=_CUTOFF.isoformat(), adjusted=True)
    assert len(bars) == len(_weekdays(lo, mid))
    # retry policy is bounded: the fake recorded a small, finite number of attempts
    assert 1 <= len(fake_provider.calls) <= settings.INGEST_MAX_RETRIES + 2

