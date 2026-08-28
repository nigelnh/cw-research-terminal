from __future__ import annotations

import asyncio
from datetime import date, timedelta

import pytest
from sqlalchemy import func, select

from app.persistence.database import session_scope
from app.persistence.ingestion.gaps import detect_gaps, repair_gaps
from app.persistence.ingestion.locks import stream_lock
from app.persistence.models import MarketBar
from app.persistence.repositories.instrument_repository import InstrumentRepository, InstrumentUpsert
from app.persistence.rows import BarUpsert
from app.persistence.repositories.market_bar_repository import MarketBarRepository
from app.persistence.market_time import VN_TZ
from datetime import datetime, timezone

pytestmark = pytest.mark.asyncio
_TODAY = date.today()


async def _seed_stock(sym="HPG") -> int:
    async with session_scope() as s:
        return (await InstrumentRepository(s).upsert(InstrumentUpsert(symbol=sym, instrument_type="STOCK"))).id


async def _put_bars(iid: int, days: list[date], pb="ADJUSTED"):
    rows = [
        BarUpsert(
            instrument_id=iid, timeframe="1d",
            ts=datetime(d.year, d.month, d.day, 0, 0, tzinfo=VN_TZ).astimezone(timezone.utc),
            open=10, high=11, low=9, close=10, volume=1, price_basis=pb, source="fiinquant",
        )
        for d in days
    ]
    async with session_scope() as s:
        await MarketBarRepository(s).bulk_upsert_bars(rows)


# ---- gap detection --------------------------------------------------------
async def test_weekend_is_not_flagged_and_isolated_missing_weekday_is_suspicious(ingestion_service):
    iid = await _seed_stock("HPG")
    start = date(2026, 3, 2)   # Monday
    end = date(2026, 3, 13)    # Friday (two full weeks)
    all_weekdays = [start + timedelta(days=i) for i in range((end - start).days + 1) if (start + timedelta(days=i)).weekday() < 5]
    missing_one = date(2026, 3, 5)   # a Thursday
    await _put_bars(iid, [d for d in all_weekdays if d != missing_one])

    report = await detect_gaps(
        ingestion_service, symbol="HPG", timeframe="1D", adjusted=True, from_date=start, to_date=end
    )
    assert report.seeded and report.expected_sessions == len(all_weekdays)
    assert len(report.suspicious) == 1
    seg = report.suspicious[0]
    assert seg.start == missing_one and seg.end == missing_one and seg.missing_days == 1
    assert report.unknown_calendar == []   # no weekend reported


async def test_multi_day_cluster_is_unknown_calendar(ingestion_service):
    iid = await _seed_stock("FPT")
    start = date(2026, 3, 2)
    end = date(2026, 3, 20)
    weekdays = [start + timedelta(days=i) for i in range((end - start).days + 1) if (start + timedelta(days=i)).weekday() < 5]
    # drop a run of 4 consecutive weekdays (Mon-Thu of week 2)
    hole = {date(2026, 3, 9), date(2026, 3, 10), date(2026, 3, 11), date(2026, 3, 12)}
    await _put_bars(iid, [d for d in weekdays if d not in hole])

    report = await detect_gaps(
        ingestion_service, symbol="FPT", timeframe="1D", adjusted=True, from_date=start, to_date=end
    )
    assert len(report.unknown_calendar) == 1
    assert report.unknown_calendar[0].missing_days == 4
    assert report.suspicious == []


async def test_tet_window_missing_days_are_unknown_calendar(ingestion_service):
    iid = await _seed_stock("SSI")
    start = date(2026, 2, 9)
    end = date(2026, 2, 27)
    weekdays = [start + timedelta(days=i) for i in range((end - start).days + 1) if (start + timedelta(days=i)).weekday() < 5]
    tet_missing = {date(2026, 2, 17), date(2026, 2, 18)}  # inside the 2026 Tet window
    await _put_bars(iid, [d for d in weekdays if d not in tet_missing])

    report = await detect_gaps(
        ingestion_service, symbol="SSI", timeframe="1D", adjusted=True, from_date=start, to_date=end
    )
    assert len(report.unknown_calendar) == 1
    assert report.suspicious == []


async def test_repair_only_refetches_suspicious_ranges_and_never_deletes(ingestion_service, fake_provider):
    iid = await _seed_stock("HPG")
    start = date(2026, 3, 2)
    end = date(2026, 3, 13)
    weekdays = [start + timedelta(days=i) for i in range((end - start).days + 1) if (start + timedelta(days=i)).weekday() < 5]
    present = [d for d in weekdays if d != date(2026, 3, 5)]
    await _put_bars(iid, present)
    before_count = await _bar_count(iid)

    fake_provider.seed_daily("HPG", start - timedelta(days=5), end + timedelta(days=5))
    result = await repair_gaps(
        ingestion_service, symbol="HPG", timeframe="1D", adjusted=True, from_date=start, to_date=end
    )
    assert result.backfill_status == "SUCCEEDED"
    assert result.after is not None and len(result.after.suspicious) == 0
    assert await _bar_count(iid) == before_count + 1     # the one missing day filled, nothing deleted


async def test_repair_dry_run_makes_no_calls(ingestion_service, fake_provider):
    iid = await _seed_stock("HPG")
    await _put_bars(iid, [date(2026, 3, 2), date(2026, 3, 4)])  # 03-03 missing
    result = await repair_gaps(
        ingestion_service, symbol="HPG", timeframe="1D", adjusted=True,
        from_date=date(2026, 3, 2), to_date=date(2026, 3, 4), dry_run=True,
    )
    assert result.dry_run and result.backfill_status == "DRY_RUN"
    assert fake_provider.calls == []


async def _bar_count(iid: int, pb="ADJUSTED") -> int:
    async with session_scope() as s:
        return int((await s.execute(select(func.count()).select_from(MarketBar).where(
            MarketBar.instrument_id == iid, MarketBar.price_basis == pb))).scalar_one())


# ---- advisory locks / overlapping runs ----------------------------------
async def test_overlapping_runs_one_is_locked_skipped_no_duplicate_data(engine, sessionmaker_, fake_provider):
    from app.persistence.ingestion.retry import RetryPolicy
    from app.persistence.ingestion.service import IngestionService

    iid = await _seed_stock("HPG")
    fake_provider.seed_daily("HPG", _TODAY - timedelta(days=40), _TODAY)

    def _mk():
        return IngestionService(
            engine=engine, sessionmaker=sessionmaker_, bar_provider=fake_provider, source="fiinquant",
            retry_policy=RetryPolicy(2, 0.0, 0.0),
        )

    svc_a, svc_b = _mk(), _mk()
    frm, to = _TODAY - timedelta(days=40), _TODAY - timedelta(days=1)
    res_a, res_b = await asyncio.gather(
        svc_a.backfill(["HPG"], timeframe="1D", adjusted=True, from_date=frm, to_date=to),
        svc_b.backfill(["HPG"], timeframe="1D", adjusted=True, from_date=frm, to_date=to),
    )
    statuses = sorted([res_a.streams[0].status, res_b.streams[0].status])
    assert "LOCKED_SKIPPED" in statuses           # exactly one blocked
    assert "SUCCEEDED" in statuses or "PARTIAL" in statuses

    async with session_scope() as s:
        weekdays = sum(1 for i in range((to - frm).days + 1) if (frm + timedelta(days=i)).weekday() < 5)
        n = (await s.execute(select(func.count()).select_from(MarketBar).where(MarketBar.instrument_id == iid))).scalar_one()
    assert n == weekdays                          # no duplicates


async def test_stream_lock_context_releases(engine):
    iid = await _seed_stock("HPG")
    async with stream_lock(engine, source="fiinquant", instrument_id=iid, timeframe="1d", price_basis="ADJUSTED") as a:
        assert a is True
        async with stream_lock(engine, source="fiinquant", instrument_id=iid, timeframe="1d", price_basis="ADJUSTED") as b:
            assert b is False           # re-entrant attempt on a different connection fails
    # released now
    async with stream_lock(engine, source="fiinquant", instrument_id=iid, timeframe="1d", price_basis="ADJUSTED") as c:
        assert c is True
