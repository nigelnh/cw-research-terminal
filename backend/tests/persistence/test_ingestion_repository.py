from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import update

from app.persistence.models import IngestionRun

from app.persistence.repositories.ingestion_repository import IngestionRepository
from app.persistence.repositories.instrument_repository import InstrumentRepository, InstrumentUpsert

pytestmark = pytest.mark.asyncio


async def test_run_lifecycle(db):
    repo = IngestionRepository(db)
    async with db.begin():
        run = await repo.start_run(
            source="fiinquant", timeframe="1D", price_basis="ADJUSTED",
            requested_symbols=["hpg", "fpt"],
            requested_from=datetime(2024, 1, 1, tzinfo=timezone.utc),
            requested_to=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
    assert run.status == "RUNNING"
    assert run.requested_symbols == ["HPG", "FPT"]
    assert run.timeframe == "1d"
    assert run.completed_at is None

    async with db.begin():
        done = await repo.complete_run(
            run.id, status="SUCCEEDED", rows_fetched=1000, rows_inserted=950, rows_updated=50
        )
    assert done.status == "SUCCEEDED"
    assert (done.rows_fetched, done.rows_inserted, done.rows_updated) == (1000, 950, 50)
    assert done.completed_at is not None

    async with db.begin():
        recent = await repo.recent_runs()
    assert recent[0].id == run.id


async def test_complete_run_rejects_running_status(db):
    repo = IngestionRepository(db)
    async with db.begin():
        run = await repo.start_run(
            source="fiinquant", timeframe="1d", price_basis="RAW", requested_symbols=["HPG"]
        )
    with pytest.raises(ValueError):
        async with db.begin():
            await repo.complete_run(run.id, status="RUNNING")


async def test_fail_orphaned_runs_only_touches_old_running_rows(db):
    repo = IngestionRepository(db)
    async with db.begin():
        stale = await repo.start_run(source="fiinquant", timeframe="1d", price_basis="RAW", requested_symbols=["HPG"])
        fresh = await repo.start_run(source="fiinquant", timeframe="1d", price_basis="RAW", requested_symbols=["NVL"])
        done = await repo.start_run(source="fiinquant", timeframe="1d", price_basis="RAW", requested_symbols=["VHM"])
    async with db.begin():
        await repo.complete_run(done.id, status="SUCCEEDED")
        # Backdate the stale run's start well past the sweep cutoff.
        await db.execute(
            update(IngestionRun).where(IngestionRun.id == stale.id)
            .values(started_at=datetime.now(timezone.utc) - timedelta(hours=3))
        )

    async with db.begin():
        n = await repo.fail_orphaned_runs(older_than_minutes=30)
    assert n == 1

    async with db.begin():
        assert (await repo.get_run(stale.id)).status == "FAILED"
        assert (await repo.get_run(stale.id)).completed_at is not None
        assert (await repo.get_run(fresh.id)).status == "RUNNING"   # too recent - untouched
        assert (await repo.get_run(done.id)).status == "SUCCEEDED"  # already terminal - untouched

    # Idempotent: a second sweep finds nothing.
    async with db.begin():
        assert await repo.fail_orphaned_runs(older_than_minutes=30) == 0


async def test_ingestion_state_upsert_and_unique_key(db):
    inst_repo = InstrumentRepository(db)
    ing = IngestionRepository(db)
    async with db.begin():
        hpg = await inst_repo.upsert(InstrumentUpsert(symbol="HPG", instrument_type="STOCK"))

    t1 = datetime(2026, 8, 20, 2, 15, tzinfo=timezone.utc)
    async with db.begin():
        s1 = await ing.upsert_state(
            source="fiinquant", instrument_id=hpg.id, timeframe="1d", price_basis="ADJUSTED",
            last_bar_ts=t1, last_success_at=t1,
        )
    assert s1.last_bar_ts == t1

    t2 = datetime(2026, 8, 21, 2, 15, tzinfo=timezone.utc)
    async with db.begin():
        s2 = await ing.upsert_state(
            source="fiinquant", instrument_id=hpg.id, timeframe="1d", price_basis="ADJUSTED",
            last_bar_ts=t2,
        )
        fetched = await ing.get_state(
            source="fiinquant", instrument_id=hpg.id, timeframe="1d", price_basis="ADJUSTED"
        )
    assert s2.id == s1.id                 # same logical cursor row
    assert s2.last_bar_ts == t2
    assert fetched is not None and fetched.last_bar_ts == t2

    # a different price_basis is a different cursor
    async with db.begin():
        s_raw = await ing.upsert_state(
            source="fiinquant", instrument_id=hpg.id, timeframe="1d", price_basis="RAW", last_bar_ts=t2
        )
    assert s_raw.id != s1.id


async def test_ingestion_state_missing_returns_none(db):
    inst_repo = InstrumentRepository(db)
    ing = IngestionRepository(db)
    async with db.begin():
        hpg = await inst_repo.upsert(InstrumentUpsert(symbol="HPG", instrument_type="STOCK"))
        got = await ing.get_state(
            source="fiinquant", instrument_id=hpg.id, timeframe="5m", price_basis="RAW"
        )
    assert got is None
