"""Data access for the ``market_bars`` table - bulk idempotent upserts and reads."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import Select, and_, func, literal_column, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.persistence.market_time import (
    normalize_price_basis,
    normalize_timeframe,
    price_basis_to_adjusted,
    require_aware_utc,
    vn_session_date,
)
from app.persistence.models import Instrument, MarketBar
from app.persistence.rows import BarCoverage, BarRow, BarUpsert, UpsertResult

_INSERTED_FLAG = literal_column("(xmax = 0)")  # true on INSERT, false on ON CONFLICT UPDATE


def _to_row(m: MarketBar) -> BarRow:
    return BarRow(
        instrument_id=m.instrument_id,
        timeframe=m.timeframe,
        ts=m.ts,
        session_date=m.session_date,
        price_basis=m.price_basis,
        open=float(m.open),
        high=float(m.high),
        low=float(m.low),
        close=float(m.close),
        volume=int(m.volume),
        source=m.source,
        updated_at=m.updated_at,
    )


class MarketBarRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------ #
    # Writes
    # ------------------------------------------------------------------ #
    async def bulk_upsert_bars(
        self,
        bars: Sequence[BarUpsert],
        *,
        ingestion_run_id: int | None = None,
        chunk_size: int | None = None,
    ) -> UpsertResult:
        """Insert or update many bars idempotently.

        Identity is ``(instrument_id, timeframe, ts, price_basis)``. Re-running with the
        same data is a no-op-equivalent (rows are updated in place, ``id`` stable). If the
        vendor revises a value, the existing logical bar is overwritten.

        Executed as chunked ``INSERT ... ON CONFLICT DO UPDATE`` statements inside the
        caller's transaction - one round trip per chunk, never per row.
        """
        if not bars:
            return UpsertResult(inserted=0, updated=0)

        chunk = int(chunk_size or settings.DATABASE_BULK_CHUNK_SIZE)
        if chunk < 1:
            chunk = 1

        payload: list[dict] = []
        for b in bars:
            tf = normalize_timeframe(b.timeframe)
            pb = b.price_basis.strip().upper()
            if pb not in ("ADJUSTED", "RAW"):
                raise ValueError(f"price_basis must be ADJUSTED or RAW, got {b.price_basis!r}")
            ts_utc = require_aware_utc(b.ts, field="bar.ts")
            session_date = b.session_date or vn_session_date(ts_utc)
            if b.high < b.low:
                raise ValueError(f"bar high {b.high} < low {b.low} for instrument {b.instrument_id} @ {ts_utc}")
            payload.append(
                {
                    "instrument_id": b.instrument_id,
                    "timeframe": tf,
                    "ts": ts_utc,
                    "session_date": session_date,
                    "price_basis": pb,
                    "open": b.open,
                    "high": b.high,
                    "low": b.low,
                    "close": b.close,
                    "volume": int(b.volume),
                    "source": b.source,
                    "ingestion_run_id": ingestion_run_id,
                }
            )

        # De-duplicate within the batch (last write wins) so one statement never lists the
        # same conflict target twice, which Postgres rejects.
        deduped: dict[tuple, dict] = {}
        for row in payload:
            deduped[(row["instrument_id"], row["timeframe"], row["ts"], row["price_basis"])] = row
        rows = list(deduped.values())

        inserted = 0
        updated = 0
        for i in range(0, len(rows), chunk):
            batch = rows[i : i + chunk]
            stmt = pg_insert(MarketBar).values(batch)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_market_bars_identity",
                set_={
                    "open": stmt.excluded.open,
                    "high": stmt.excluded.high,
                    "low": stmt.excluded.low,
                    "close": stmt.excluded.close,
                    "volume": stmt.excluded.volume,
                    "session_date": stmt.excluded.session_date,
                    "source": stmt.excluded.source,
                    "ingestion_run_id": stmt.excluded.ingestion_run_id,
                    "updated_at": func.now(),
                },
            ).returning(_INSERTED_FLAG.label("was_insert"))
            result = await self._session.execute(stmt)
            for (was_insert,) in result.all():
                if was_insert:
                    inserted += 1
                else:
                    updated += 1
        return UpsertResult(inserted=inserted, updated=updated)

    # ------------------------------------------------------------------ #
    # Reads
    # ------------------------------------------------------------------ #
    async def _resolve_instrument_id(self, *, instrument_id: int | None, symbol: str | None) -> int | None:
        if instrument_id is not None:
            return instrument_id
        if symbol:
            m = (
                await self._session.execute(
                    select(Instrument.id).where(Instrument.symbol == symbol.strip().upper())
                )
            ).scalar_one_or_none()
            return m
        raise ValueError("either instrument_id or symbol is required")

    def _base_filter(self, instrument_id: int, timeframe: str, price_basis: str) -> Select:
        return select(MarketBar).where(
            and_(
                MarketBar.instrument_id == instrument_id,
                MarketBar.timeframe == normalize_timeframe(timeframe),
                MarketBar.price_basis == price_basis.strip().upper(),
            )
        )

    async def get_bars(
        self,
        *,
        timeframe: str,
        instrument_id: int | None = None,
        symbol: str | None = None,
        adjusted: bool | None = None,
        price_basis: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int | None = None,
        ascending: bool = True,
    ) -> list[BarRow]:
        """Bars for one instrument + timeframe + price basis within ``[start, end)``.

        Exactly one of ``adjusted`` / ``price_basis`` must be given - a query can never
        silently mix adjusted and raw series.
        """
        if (adjusted is None) == (price_basis is None):
            raise ValueError("pass exactly one of `adjusted=` or `price_basis=`")
        pb = price_basis.strip().upper() if price_basis is not None else normalize_price_basis(adjusted=bool(adjusted))

        resolved = await self._resolve_instrument_id(instrument_id=instrument_id, symbol=symbol)
        if resolved is None:
            return []

        stmt = self._base_filter(resolved, timeframe, pb)
        if start is not None:
            stmt = stmt.where(MarketBar.ts >= require_aware_utc(start, field="start"))
        if end is not None:
            stmt = stmt.where(MarketBar.ts < require_aware_utc(end, field="end"))
        stmt = stmt.order_by(MarketBar.ts.asc() if ascending else MarketBar.ts.desc())
        if limit is not None:
            stmt = stmt.limit(int(limit))
        return [_to_row(m) for m in (await self._session.execute(stmt)).scalars().all()]

    async def latest_bar_ts(
        self, *, instrument_id: int, timeframe: str, adjusted: bool | None = None, price_basis: str | None = None
    ) -> datetime | None:
        pb = _resolve_pb(adjusted, price_basis)
        stmt = select(func.max(MarketBar.ts)).where(
            and_(
                MarketBar.instrument_id == instrument_id,
                MarketBar.timeframe == normalize_timeframe(timeframe),
                MarketBar.price_basis == pb,
            )
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def earliest_bar_ts(
        self, *, instrument_id: int, timeframe: str, adjusted: bool | None = None, price_basis: str | None = None
    ) -> datetime | None:
        pb = _resolve_pb(adjusted, price_basis)
        stmt = select(func.min(MarketBar.ts)).where(
            and_(
                MarketBar.instrument_id == instrument_id,
                MarketBar.timeframe == normalize_timeframe(timeframe),
                MarketBar.price_basis == pb,
            )
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def count_bars(
        self, *, instrument_id: int, timeframe: str, adjusted: bool | None = None, price_basis: str | None = None
    ) -> int:
        pb = _resolve_pb(adjusted, price_basis)
        stmt = select(func.count()).select_from(MarketBar).where(
            and_(
                MarketBar.instrument_id == instrument_id,
                MarketBar.timeframe == normalize_timeframe(timeframe),
                MarketBar.price_basis == pb,
            )
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def coverage(
        self, *, instrument_id: int, timeframe: str, adjusted: bool | None = None, price_basis: str | None = None
    ) -> BarCoverage:
        """earliest ts, latest ts and count in a single round trip."""
        pb = _resolve_pb(adjusted, price_basis)
        tf = normalize_timeframe(timeframe)
        stmt = select(
            func.min(MarketBar.ts), func.max(MarketBar.ts), func.count()
        ).where(
            and_(
                MarketBar.instrument_id == instrument_id,
                MarketBar.timeframe == tf,
                MarketBar.price_basis == pb,
            )
        )
        earliest, latest, cnt = (await self._session.execute(stmt)).one()
        return BarCoverage(
            instrument_id=instrument_id,
            timeframe=tf,
            price_basis=pb,
            earliest_ts=earliest,
            latest_ts=latest,
            bar_count=int(cnt),
        )

    async def has_bar(
        self, *, instrument_id: int, timeframe: str, ts: datetime, adjusted: bool | None = None, price_basis: str | None = None
    ) -> bool:
        pb = _resolve_pb(adjusted, price_basis)
        stmt = select(func.count()).select_from(MarketBar).where(
            and_(
                MarketBar.instrument_id == instrument_id,
                MarketBar.timeframe == normalize_timeframe(timeframe),
                MarketBar.price_basis == pb,
                MarketBar.ts == require_aware_utc(ts, field="ts"),
            )
        )
        return int((await self._session.execute(stmt)).scalar_one()) > 0


def _resolve_pb(adjusted: bool | None, price_basis: str | None) -> str:
    if (adjusted is None) == (price_basis is None):
        raise ValueError("pass exactly one of `adjusted=` or `price_basis=`")
    if price_basis is not None:
        pb = price_basis.strip().upper()
        if pb not in ("ADJUSTED", "RAW"):
            raise ValueError(f"unknown price_basis {price_basis!r}")
        return pb
    return normalize_price_basis(adjusted=bool(adjusted))


__all__ = ["MarketBarRepository", "price_basis_to_adjusted"]
