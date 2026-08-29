"""Data access for ``instrument_snapshots`` — the last-valid market snapshot store.

Idempotent, session-scoped writes. Guarantees:
  * exactly one row per (symbol, session_date), upserted;
  * a row is NEVER regressed to an older session by a late write;
  * within a session, ``captured_at`` only advances and ``quality`` never downgrades
    FINAL -> INTRADAY_CHECKPOINT / SEED.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.persistence.models import InstrumentSnapshot

_QUALITY_RANK = {"SEED": 0, "INTRADAY_CHECKPOINT": 1, "FINAL": 2}


@dataclass
class SnapshotRow:
    symbol: str
    session_date: date
    captured_at: datetime
    source: str            # REALTIME_CHECKPOINT | SESSION_CLOSE | HISTORICAL_SEED
    quality: str           # FINAL | INTRADAY_CHECKPOINT | SEED
    instrument_type: str
    reference_price: float | None = None
    last_price: float | None = None
    price_change: float | None = None
    price_change_percent: float | None = None
    open_price: float | None = None
    high_price: float | None = None
    low_price: float | None = None
    average_price: float | None = None
    total_volume: int | None = None
    trading_value: float | None = None
    bid1_price: float | None = None
    bid1_quantity: int | None = None
    ask1_price: float | None = None
    ask1_quantity: int | None = None
    bid2_price: float | None = None
    bid2_quantity: int | None = None
    ask2_price: float | None = None
    ask2_quantity: int | None = None
    bid3_price: float | None = None
    bid3_quantity: int | None = None
    ask3_price: float | None = None
    ask3_quantity: int | None = None
    underlying_symbol: str | None = None
    underlying_price: float | None = None


class SnapshotRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get_latest(self, symbol: str) -> InstrumentSnapshot | None:
        stmt = (
            select(InstrumentSnapshot)
            .where(InstrumentSnapshot.symbol == symbol.strip().upper())
            .order_by(InstrumentSnapshot.session_date.desc())
            .limit(1)
        )
        return (await self._s.execute(stmt)).scalars().first()

    async def get_many_latest(self, symbols: Iterable[str]) -> dict[str, InstrumentSnapshot]:
        syms = sorted({s.strip().upper() for s in symbols if s and s.strip()})
        if not syms:
            return {}
        stmt = (
            select(InstrumentSnapshot)
            .where(InstrumentSnapshot.symbol.in_(syms))
            .order_by(InstrumentSnapshot.symbol, InstrumentSnapshot.session_date.desc())
        )
        out: dict[str, InstrumentSnapshot] = {}
        for row in (await self._s.execute(stmt)).scalars():
            out.setdefault(row.symbol, row)  # first per symbol = newest session
        return out

    async def get_for_session(self, symbol: str, session_date: date) -> InstrumentSnapshot | None:
        stmt = select(InstrumentSnapshot).where(
            InstrumentSnapshot.symbol == symbol.strip().upper(),
            InstrumentSnapshot.session_date == session_date,
        )
        return (await self._s.execute(stmt)).scalars().first()

    async def upsert(self, row: SnapshotRow) -> None:
        """Insert or update the (symbol, session_date) row, applying the regression guards."""
        sym = row.symbol.strip().upper()
        existing_latest = await self.get_latest(sym)
        if existing_latest is not None and existing_latest.session_date > row.session_date:
            return  # never regress to an older session

        same = await self.get_for_session(sym, row.session_date)
        if same is not None:
            # A FINAL row is the canonical close for that session - later non-FINAL
            # checkpoints (e.g. a stray post-close tick) must not overwrite it.
            if same.quality == "FINAL" and row.quality != "FINAL":
                return
            newer = row.captured_at > same.captured_at
            better = _QUALITY_RANK.get(row.quality, 0) > _QUALITY_RANK.get(same.quality, 0)
            if not newer and not better:
                return  # nothing newer / better to record

        values: dict[str, Any] = asdict(row)
        values["symbol"] = sym
        # Keep whichever quality label is higher-ranked (FINAL never downgrades).
        if same is not None:
            values["quality"] = row.quality if _QUALITY_RANK.get(row.quality, 0) >= _QUALITY_RANK.get(same.quality, 0) else same.quality

        update_cols: dict[str, Any] = {
            k: getattr(pg_insert(InstrumentSnapshot).excluded, k)
            for k in values
            if k not in ("symbol", "session_date")
        }
        update_cols["updated_at"] = datetime.now(tz=row.captured_at.tzinfo)

        stmt = pg_insert(InstrumentSnapshot).values(**values)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_instrument_snapshots_symbol_session",
            set_=update_cols,
        )
        await self._s.execute(stmt)
