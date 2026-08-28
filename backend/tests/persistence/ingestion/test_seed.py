from __future__ import annotations

import pytest

from app.persistence.database import session_scope
from app.persistence.ingestion.seed import seed_instruments
from app.persistence.repositories.instrument_repository import InstrumentRepository

pytestmark = pytest.mark.asyncio

_REGISTRY_DATE = "2026-08-25"


async def _instrument_count(itype: str | None = None) -> int:
    from sqlalchemy import func, select

    from app.persistence.models import Instrument

    async with session_scope() as s:
        stmt = select(func.count()).select_from(Instrument)
        if itype:
            stmt = stmt.where(Instrument.instrument_type == itype)
        return int((await s.execute(stmt)).scalar_one())


async def test_seed_is_deterministic_and_rerunnable(engine, sessionmaker_):
    r1 = await seed_instruments(registry_current_date=_REGISTRY_DATE)
    total1 = await _instrument_count()
    ids1 = await _all_ids()

    r2 = await seed_instruments(registry_current_date=_REGISTRY_DATE)
    total2 = await _instrument_count()
    ids2 = await _all_ids()

    assert total1 == total2 == r1.total == r2.total
    assert ids1 == ids2                       # stable IDs, no churn
    assert r1.warrants_seeded == r2.warrants_seeded
    assert r1.stocks_seeded > 0 and r1.warrants_seeded > 0


async def test_seed_resolves_warrant_underlyings(engine, sessionmaker_):
    report = await seed_instruments(registry_current_date=_REGISTRY_DATE)
    # every warrant that names an underlying should be linked (underlyings are seeded first)
    assert report.underlyings_resolved > 0
    assert report.warrants_unresolved_underlying == []

    async with session_scope() as s:
        repo = InstrumentRepository(s)
        # spot check a known active pair from the canonical snapshot
        cw = await repo.get_by_symbol("CHPG2602")
        hpg = await repo.get_by_symbol("HPG")
        assert cw is not None and hpg is not None
        assert cw.underlying_instrument_id == hpg.id
        assert cw.instrument_type == "CW"
        assert hpg.instrument_type == "STOCK"


async def test_seed_includes_inactive_and_partial_warrants(engine, sessionmaker_):
    report = await seed_instruments(registry_current_date=_REGISTRY_DATE)
    # the canonical snapshot has EXPIRED / UNKNOWN warrants - they still get rows
    assert report.inactive_count > 0
    assert report.active_count > 0

    async with session_scope() as s:
        repo = InstrumentRepository(s)
        active = await repo.list_active("CW")
        assert 0 < len(active) < report.warrants_seeded   # some but not all CWs are active

        expired = await repo.get_by_symbol("CFPT2401")   # EXPIRED in the snapshot
        assert expired is not None and expired.is_active is False
        assert "lifecycle_status" in expired.metadata    # compact provenance, not the whole record
        assert "provenance" not in expired.metadata


async def test_seed_indices_optional(engine, sessionmaker_):
    await seed_instruments(registry_current_date=_REGISTRY_DATE, include_indices=False)
    assert await _instrument_count("INDEX") == 0
    await seed_instruments(registry_current_date=_REGISTRY_DATE, include_indices=True)
    assert await _instrument_count("INDEX") >= 3


async def _all_ids() -> dict[str, int]:
    from sqlalchemy import select

    from app.persistence.models import Instrument

    async with session_scope() as s:
        rows = (await s.execute(select(Instrument.symbol, Instrument.id))).all()
    return {r[0]: r[1] for r in rows}
