from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.persistence.market_time import VN_TZ
from app.persistence.repositories.instrument_repository import InstrumentRepository, InstrumentUpsert
from app.persistence.repositories.market_bar_repository import MarketBarRepository
from app.persistence.rows import BarUpsert

pytestmark = pytest.mark.asyncio


async def _instrument(db, symbol="HPG", itype="STOCK") -> int:
    repo = InstrumentRepository(db)
    async with db.begin():
        row = await repo.upsert(InstrumentUpsert(symbol=symbol, instrument_type=itype))
    return row.id


def _daily_bars(instrument_id, closes, *, basis="ADJUSTED", start_day=20):
    out = []
    for i, c in enumerate(closes):
        ts = datetime(2026, 8, start_day + i, 0, 0, tzinfo=VN_TZ).astimezone(timezone.utc)
        out.append(
            BarUpsert(
                instrument_id=instrument_id, timeframe="1d", ts=ts,
                open=c - 100, high=c + 200, low=c - 300, close=c, volume=1_000_000 + i,
                price_basis=basis, source="fiinquant",
            )
        )
    return out


async def test_insert_then_idempotent_reupsert(db):
    iid = await _instrument(db)
    repo = MarketBarRepository(db)
    bars = _daily_bars(iid, [27000, 27100, 26900, 27250])

    async with db.begin():
        r1 = await repo.bulk_upsert_bars(bars)
    assert (r1.inserted, r1.updated) == (4, 0)

    async with db.begin():
        r2 = await repo.bulk_upsert_bars(bars)  # exact same dataset again
    assert (r2.inserted, r2.updated) == (0, 4)   # no duplicates, rows updated in place

    async with db.begin():
        cnt = await repo.count_bars(instrument_id=iid, timeframe="1d", adjusted=True)
    assert cnt == 4


async def test_vendor_revision_updates_existing_logical_bar(db):
    iid = await _instrument(db)
    repo = MarketBarRepository(db)
    async with db.begin():
        await repo.bulk_upsert_bars(_daily_bars(iid, [27000, 27100]))

    # vendor later revises the close of the 2nd bar
    revised = _daily_bars(iid, [27000, 27199])
    async with db.begin():
        r = await repo.bulk_upsert_bars(revised)
        rows = await repo.get_bars(instrument_id=iid, timeframe="1d", adjusted=True)
    assert (r.inserted, r.updated) == (0, 2)
    assert [float(b.close) for b in rows] == [27000.0, 27199.0]
    assert len(rows) == 2


async def test_adjusted_and_raw_coexist_and_never_mix(db):
    iid = await _instrument(db)
    repo = MarketBarRepository(db)
    async with db.begin():
        await repo.bulk_upsert_bars(_daily_bars(iid, [26800, 26850], basis="ADJUSTED"))
        await repo.bulk_upsert_bars(_daily_bars(iid, [27000, 27050], basis="RAW"))

    async with db.begin():
        adj = await repo.get_bars(instrument_id=iid, timeframe="1d", price_basis="ADJUSTED")
        raw = await repo.get_bars(instrument_id=iid, timeframe="1d", price_basis="RAW")
        total = await repo.count_bars(instrument_id=iid, timeframe="1d", adjusted=True)
    assert [float(b.close) for b in adj] == [26800.0, 26850.0]
    assert [float(b.close) for b in raw] == [27000.0, 27050.0]
    assert total == 2  # count is per-basis, not combined
    assert all(b.price_basis == "ADJUSTED" for b in adj)


async def test_get_bars_requires_exactly_one_basis_selector(db):
    iid = await _instrument(db)
    repo = MarketBarRepository(db)
    with pytest.raises(ValueError):
        await repo.get_bars(instrument_id=iid, timeframe="1d")
    with pytest.raises(ValueError):
        await repo.get_bars(instrument_id=iid, timeframe="1d", adjusted=True, price_basis="RAW")


async def test_multiple_timeframes_are_independent(db):
    iid = await _instrument(db)
    repo = MarketBarRepository(db)
    base = datetime(2026, 8, 20, 9, 15, tzinfo=VN_TZ).astimezone(timezone.utc)
    intraday = [
        BarUpsert(instrument_id=iid, timeframe="5m", ts=base + timedelta(minutes=5 * i),
                  open=100, high=101, low=99, close=100 + i, volume=500, price_basis="RAW", source="fiinquant")
        for i in range(6)
    ]
    async with db.begin():
        await repo.bulk_upsert_bars(_daily_bars(iid, [27000], basis="RAW"))
        await repo.bulk_upsert_bars(intraday)

    async with db.begin():
        d = await repo.count_bars(instrument_id=iid, timeframe="1d", price_basis="RAW")
        m5 = await repo.count_bars(instrument_id=iid, timeframe="5m", price_basis="RAW")
    assert (d, m5) == (1, 6)


async def test_time_range_query_is_half_open(db):
    iid = await _instrument(db)
    repo = MarketBarRepository(db)
    async with db.begin():
        await repo.bulk_upsert_bars(_daily_bars(iid, [1000, 1001, 1002, 1003, 1004]))  # Aug 20..24 VN

    lo = datetime(2026, 8, 21, 0, 0, tzinfo=VN_TZ).astimezone(timezone.utc)
    hi = datetime(2026, 8, 24, 0, 0, tzinfo=VN_TZ).astimezone(timezone.utc)
    async with db.begin():
        rows = await repo.get_bars(instrument_id=iid, timeframe="1d", adjusted=True, start=lo, end=hi)
    # [lo, hi): Aug 21, 22, 23  (not 24)
    assert [b.session_date.isoformat() for b in rows] == ["2026-08-21", "2026-08-22", "2026-08-23"]


async def test_latest_earliest_and_coverage(db):
    iid = await _instrument(db)
    repo = MarketBarRepository(db)
    bars = _daily_bars(iid, [1, 2, 3, 4, 5])
    async with db.begin():
        await repo.bulk_upsert_bars(bars)
        latest = await repo.latest_bar_ts(instrument_id=iid, timeframe="1d", adjusted=True)
        earliest = await repo.earliest_bar_ts(instrument_id=iid, timeframe="1d", adjusted=True)
        cov = await repo.coverage(instrument_id=iid, timeframe="1d", adjusted=True)
        none_raw = await repo.latest_bar_ts(instrument_id=iid, timeframe="1d", price_basis="RAW")
    assert earliest == bars[0].ts
    assert latest == bars[-1].ts
    assert cov.bar_count == 5 and cov.earliest_ts == bars[0].ts and cov.latest_ts == bars[-1].ts
    assert none_raw is None


async def test_naive_datetime_is_rejected_at_boundary(db):
    iid = await _instrument(db)
    repo = MarketBarRepository(db)
    bad = BarUpsert(
        instrument_id=iid, timeframe="1d", ts=datetime(2026, 8, 20, 0, 0),  # naive
        open=1, high=2, low=1, close=2, volume=1, price_basis="RAW", source="fiinquant",
    )
    with pytest.raises(ValueError):
        async with db.begin():
            await repo.bulk_upsert_bars([bad])


async def test_bulk_upsert_chunks_many_rows(db):
    iid = await _instrument(db)
    repo = MarketBarRepository(db)
    base = datetime(2026, 1, 1, 9, 15, tzinfo=VN_TZ).astimezone(timezone.utc)
    many = [
        BarUpsert(instrument_id=iid, timeframe="1m", ts=base + timedelta(minutes=i),
                  open=10, high=11, low=9, close=10, volume=1, price_basis="RAW", source="fiinquant")
        for i in range(2500)
    ]
    async with db.begin():
        r = await repo.bulk_upsert_bars(many, chunk_size=500)
    assert (r.inserted, r.updated) == (2500, 0)
    async with db.begin():
        assert await repo.count_bars(instrument_id=iid, timeframe="1m", price_basis="RAW") == 2500
