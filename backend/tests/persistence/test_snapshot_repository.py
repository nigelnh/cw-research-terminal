"""instrument_snapshots repository - idempotency + session-regression + quality guards."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app.persistence.repositories.snapshot_repository import SnapshotRepository, SnapshotRow

pytestmark = pytest.mark.asyncio

_VN = timezone(timedelta(hours=7))


def _row(sym, sd, *, at, quality="INTRADAY_CHECKPOINT", source="REALTIME_CHECKPOINT", last=100.0, bid=None, ask=None):
    return SnapshotRow(
        symbol=sym, session_date=sd, captured_at=at, source=source, quality=quality,
        instrument_type="CW", last_price=last, bid1_price=bid, ask1_price=ask,
    )


async def test_upsert_is_idempotent(sessionmaker_):
    sd = date(2026, 8, 28)
    async with sessionmaker_() as s:
        repo = SnapshotRepository(s)
        await repo.upsert(_row("CVPB2615", sd, at=datetime(2026, 8, 28, 14, 0, tzinfo=_VN)))
        await repo.upsert(_row("CVPB2615", sd, at=datetime(2026, 8, 28, 14, 0, tzinfo=_VN)))
        await s.commit()
        got = await repo.get_latest("CVPB2615")
        assert got is not None and got.session_date == sd
        rows = await repo.get_many_latest(["CVPB2615"])
        assert len(rows) == 1


async def test_captured_at_only_advances(sessionmaker_):
    sd = date(2026, 8, 28)
    async with sessionmaker_() as s:
        repo = SnapshotRepository(s)
        await repo.upsert(_row("HPG", sd, at=datetime(2026, 8, 28, 14, 30, tzinfo=_VN), last=101.0))
        await repo.upsert(_row("HPG", sd, at=datetime(2026, 8, 28, 14, 0, tzinfo=_VN), last=999.0))  # older
        await s.commit()
        got = await repo.get_latest("HPG")
        assert got is not None and float(got.last_price) == 101.0


async def test_never_regress_to_older_session(sessionmaker_):
    async with sessionmaker_() as s:
        repo = SnapshotRepository(s)
        await repo.upsert(_row("HPG", date(2026, 8, 28), at=datetime(2026, 8, 28, 15, 0, tzinfo=_VN), last=110.0))
        await repo.upsert(_row("HPG", date(2026, 8, 27), at=datetime(2026, 8, 28, 16, 0, tzinfo=_VN), last=90.0))
        await s.commit()
        got = await repo.get_latest("HPG")
        assert got is not None and got.session_date == date(2026, 8, 28)


async def test_final_quality_never_downgraded(sessionmaker_):
    sd = date(2026, 8, 28)
    async with sessionmaker_() as s:
        repo = SnapshotRepository(s)
        await repo.upsert(_row("HPG", sd, at=datetime(2026, 8, 28, 15, 5, tzinfo=_VN),
                               quality="FINAL", source="SESSION_CLOSE", bid=99.0, ask=101.0))
        await repo.upsert(_row("HPG", sd, at=datetime(2026, 8, 28, 15, 30, tzinfo=_VN),
                               quality="INTRADAY_CHECKPOINT"))
        await s.commit()
        got = await repo.get_latest("HPG")
        assert got is not None and got.quality == "FINAL"
        assert float(got.bid1_price) == 99.0  # book from the FINAL row retained
