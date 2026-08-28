from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import func, select

from app.persistence.database import session_scope
from app.persistence.models import MarketBar
from app.persistence.repositories.instrument_repository import InstrumentRepository, InstrumentUpsert

pytestmark = pytest.mark.asyncio
_TODAY = date.today()


async def _seed_stock(sym="HPG") -> int:
    async with session_scope() as s:
        return (await InstrumentRepository(s).upsert(InstrumentUpsert(symbol=sym, instrument_type="STOCK"))).id


async def _count(iid: int, pb="ADJUSTED") -> int:
    async with session_scope() as s:
        return int(
            (await s.execute(select(func.count()).select_from(MarketBar).where(
                MarketBar.instrument_id == iid, MarketBar.price_basis == pb))).scalar_one()
        )


async def test_incremental_fetches_only_the_tail_with_overlap(ingestion_service, fake_provider):
    iid = await _seed_stock("HPG")
    fake_provider.seed_daily("HPG", _TODAY - timedelta(days=120), _TODAY)

    # initial partial backfill up to 30 days ago
    await ingestion_service.backfill(
        ["HPG"], timeframe="1D", adjusted=True,
        from_date=_TODAY - timedelta(days=120), to_date=_TODAY - timedelta(days=30),
    )
    before = await _count(iid)
    fake_provider.calls.clear()

    res = await ingestion_service.incremental(["HPG"], timeframe="1D", adjusted=True)
    assert res.status == "SUCCEEDED"
    # exactly one provider call, and its window starts within `overlap` days of the last bar
    assert len(fake_provider.calls) == 1
    _, _, f_iso, _t_iso, _ = fake_provider.calls[0]
    req_from = date.fromisoformat(f_iso)
    assert (_TODAY - timedelta(days=30)) - timedelta(days=10) <= req_from <= (_TODAY - timedelta(days=30))
    assert await _count(iid) > before


async def test_incremental_when_already_current_is_a_noop(ingestion_service, fake_provider):
    await _seed_stock("FPT")
    fake_provider.seed_daily("FPT", _TODAY - timedelta(days=60), _TODAY)
    # backfill through today: whatever `last_completed_session_date()` is (time-of-day
    # dependent), it is already covered, so a subsequent incremental inserts nothing.
    await ingestion_service.backfill(
        ["FPT"], timeframe="1D", adjusted=True,
        from_date=_TODAY - timedelta(days=60), to_date=_TODAY,
    )
    fake_provider.calls.clear()
    res = await ingestion_service.incremental(["FPT"], timeframe="1D", adjusted=True)
    # overlap re-fetch is allowed, but no new rows and status SUCCEEDED
    assert res.status == "SUCCEEDED"
    assert all(c.inserted == 0 for s in res.streams for c in s.chunks)


async def test_incremental_from_empty_does_bounded_first_fill(ingestion_service, fake_provider):
    iid = await _seed_stock("SSI")
    fake_provider.seed_daily("SSI", _TODAY - timedelta(days=500), _TODAY)
    res = await ingestion_service.incremental(["SSI"], timeframe="1D", adjusted=True)
    assert res.status == "SUCCEEDED"
    async with session_scope() as s:
        earliest = (await s.execute(select(func.min(MarketBar.session_date)).where(MarketBar.instrument_id == iid))).scalar_one()
    # never reaches past the ~1-year entitlement horizon
    assert earliest is not None and earliest >= _TODAY - timedelta(days=365)


async def test_incremental_dry_run_no_calls_no_writes(ingestion_service, fake_provider):
    await _seed_stock("HPG")
    fake_provider.seed_daily("HPG", _TODAY - timedelta(days=30), _TODAY)
    res = await ingestion_service.incremental(["HPG"], timeframe="1D", adjusted=True, dry_run=True)
    assert res.status == "DRY_RUN"
    assert fake_provider.calls == []
    async with session_scope() as s:
        assert (await s.execute(select(func.count()).select_from(MarketBar))).scalar_one() == 0
