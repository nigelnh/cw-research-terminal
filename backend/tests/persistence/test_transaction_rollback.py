"""Real PostgreSQL transaction semantics: a failed statement rolls the whole batch back."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.persistence.market_time import VN_TZ
from app.persistence.repositories.instrument_repository import InstrumentRepository, InstrumentUpsert
from app.persistence.repositories.market_bar_repository import MarketBarRepository
from app.persistence.rows import BarUpsert

pytestmark = pytest.mark.asyncio


async def test_partial_failure_rolls_back_every_row(db):
    repo_i = InstrumentRepository(db)
    async with db.begin():
        iid = (await repo_i.upsert(InstrumentUpsert(symbol="HPG", instrument_type="STOCK"))).id

    repo_b = MarketBarRepository(db)
    good = BarUpsert(
        instrument_id=iid, timeframe="1d",
        ts=datetime(2026, 8, 20, 0, 0, tzinfo=VN_TZ).astimezone(timezone.utc),
        open=1, high=2, low=1, close=2, volume=1, price_basis="RAW", source="fiinquant",
    )
    # references a non-existent instrument -> FK violation at flush time
    bad = BarUpsert(
        instrument_id=999_999, timeframe="1d",
        ts=datetime(2026, 8, 21, 0, 0, tzinfo=VN_TZ).astimezone(timezone.utc),
        open=1, high=2, low=1, close=2, volume=1, price_basis="RAW", source="fiinquant",
    )

    with pytest.raises(IntegrityError):
        async with db.begin():
            await repo_b.bulk_upsert_bars([good, bad])

    # the good row must NOT have survived
    async with db.begin():
        cnt = await repo_b.count_bars(instrument_id=iid, timeframe="1d", price_basis="RAW")
    assert cnt == 0


async def test_check_constraint_violation_aborts_transaction(db):
    repo_i = InstrumentRepository(db)
    async with db.begin():
        iid = (await repo_i.upsert(InstrumentUpsert(symbol="HPG", instrument_type="STOCK"))).id

    repo_b = MarketBarRepository(db)
    # high < low is blocked in Python by the repo, so hit the DB CHECK directly via raw values
    from sqlalchemy import text

    with pytest.raises(IntegrityError):
        async with db.begin():
            await db.execute(
                text(
                    "INSERT INTO market_bars "
                    "(instrument_id,timeframe,ts,session_date,price_basis,open,high,low,close,volume,source) "
                    "VALUES (:iid,'1d','2026-08-20T00:00:00Z','2026-08-20','RAW',1,1,9,1,1,'fiinquant')"
                ),
                {"iid": iid},
            )

    async with db.begin():
        assert await repo_b.count_bars(instrument_id=iid, timeframe="1d", price_basis="RAW") == 0
