"""PostgresHistoricalBarSource satisfies the HistoricalBarSource protocol and feeds
HistoricalVolatilityService without any change to that service or LiveQuantEngine.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone

import pytest

from app.persistence.bar_source import PostgresHistoricalBarSource
from app.persistence.market_time import VN_TZ
from app.persistence.repositories.instrument_repository import InstrumentRepository, InstrumentUpsert
from app.persistence.repositories.market_bar_repository import MarketBarRepository
from app.persistence.rows import BarUpsert
from app.quant.historical_volatility_service import HistoricalVolatilityService

pytestmark = pytest.mark.asyncio

_DAY0 = datetime(2026, 1, 5, 0, 0, tzinfo=VN_TZ).astimezone(timezone.utc)


async def _seed_daily(db, symbol: str, closes: list[float], *, basis: str = "ADJUSTED") -> int:
    irepo = InstrumentRepository(db)
    brepo = MarketBarRepository(db)
    async with db.begin():
        row = await irepo.upsert(InstrumentUpsert(symbol=symbol, instrument_type="STOCK"))
        bars = [
            BarUpsert(
                instrument_id=row.id, timeframe="1d", ts=_DAY0 + timedelta(days=i),
                open=c, high=c * 1.01, low=c * 0.99, close=c, volume=1_000_000,
                price_basis=basis, source="fiinquant",
            )
            for i, c in enumerate(closes)
        ]
        await brepo.bulk_upsert_bars(bars)
    return row.id


async def test_bar_source_returns_persisted_adjusted_series_in_order(db, sessionmaker_):
    closes = [100.0, 101.0, 99.5, 102.0, 100.5, 103.0]
    await _seed_daily(db, "HPG", closes)

    src = PostgresHistoricalBarSource(sessionmaker_)
    bars = await src.get_historical_bars("hpg", timeframe="1D", adjusted=True)
    assert [b.close for b in bars] == closes           # ts-ascending == insertion order
    assert all(b.adjusted for b in bars)

    raw = await src.get_historical_bars("HPG", timeframe="1D", adjusted=False)
    assert raw == []                                    # nothing persisted as RAW


async def test_bar_source_honours_date_window(db, sessionmaker_):
    await _seed_daily(db, "HPG", [10, 11, 12, 13, 14])  # 5 sessions from _DAY0
    src = PostgresHistoricalBarSource(sessionmaker_)
    win = await src.get_historical_bars(
        "HPG", timeframe="1D", adjusted=True,
        from_date="2026-01-06", to_date="2026-01-08",
    )
    # session dates are the VN dates of _DAY0..+4  == 2026-01-05..09
    assert [b.date for b in win] == ["2026-01-06", "2026-01-07", "2026-01-08"]


async def test_history_volatility_service_consumes_postgres_source(db, sessionmaker_):
    closes = [100.0 * (1.0 + 0.01 * math.sin(i / 3.0)) for i in range(40)]
    await _seed_daily(db, "FPT", closes)

    svc = HistoricalVolatilityService(bar_source=PostgresHistoricalBarSource(sessionmaker_))
    est = await svc.refresh("FPT")
    assert est is not None
    assert est.value > 0
    assert est.window == svc.window
    assert est.source_label == f"HV_{svc.window}"
    # The estimate retains the final bar date; this deliberately old fixture is stale.
    assert est.as_of == date(2026, 2, 13)
    assert svc.get_estimate("FPT") is None
