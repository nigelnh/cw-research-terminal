"""Data access for the ``instruments`` table."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.persistence.models import Instrument
from app.persistence.rows import InstrumentRow

_VALID_TYPES = {"CW", "STOCK", "INDEX"}


@dataclass(frozen=True, slots=True)
class InstrumentUpsert:
    symbol: str
    instrument_type: str
    exchange: str = "HOSE"
    currency: str = "VND"
    underlying_symbol: str | None = None
    is_active: bool = True
    first_trade_date: date | None = None
    last_trade_date: date | None = None
    metadata: dict | None = None


def _to_row(m: Instrument) -> InstrumentRow:
    return InstrumentRow(
        id=m.id,
        symbol=m.symbol,
        instrument_type=m.instrument_type,
        exchange=m.exchange,
        currency=m.currency,
        underlying_instrument_id=m.underlying_instrument_id,
        is_active=m.is_active,
        first_trade_date=m.first_trade_date,
        last_trade_date=m.last_trade_date,
        metadata=dict(m.attributes or {}),
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


class InstrumentRepository:
    """One instance per unit of work; the caller owns the transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _clean_symbol(symbol: str) -> str:
        s = (symbol or "").strip().upper()
        if not s:
            raise ValueError("instrument symbol must be non-empty")
        return s

    async def get_by_symbol(self, symbol: str) -> InstrumentRow | None:
        s = self._clean_symbol(symbol)
        m = (await self._session.execute(select(Instrument).where(Instrument.symbol == s))).scalar_one_or_none()
        return _to_row(m) if m is not None else None

    async def get_by_id(self, instrument_id: int) -> InstrumentRow | None:
        m = await self._session.get(Instrument, instrument_id)
        return _to_row(m) if m is not None else None

    async def _resolve_underlying_id(self, underlying_symbol: str | None) -> int | None:
        if not underlying_symbol:
            return None
        row = await self.get_by_symbol(underlying_symbol)
        return row.id if row is not None else None

    async def upsert(self, spec: InstrumentUpsert) -> InstrumentRow:
        """Insert or update one instrument by ``symbol``. Row identity (``id``) is stable."""
        symbol = self._clean_symbol(spec.symbol)
        itype = spec.instrument_type.strip().upper()
        if itype not in _VALID_TYPES:
            raise ValueError(f"instrument_type must be one of {sorted(_VALID_TYPES)}, got {spec.instrument_type!r}")
        underlying_id = await self._resolve_underlying_id(spec.underlying_symbol)

        values = {
            "symbol": symbol,
            "instrument_type": itype,
            "exchange": spec.exchange.strip().upper() or "HOSE",
            "currency": spec.currency.strip().upper() or "VND",
            "underlying_instrument_id": underlying_id,
            "is_active": spec.is_active,
            "first_trade_date": spec.first_trade_date,
            "last_trade_date": spec.last_trade_date,
            "attributes": spec.metadata or {},
        }
        update_cols = {k: v for k, v in values.items() if k != "symbol"}
        # Do not clobber a previously-resolved underlying with NULL if the caller did not
        # supply one this time.
        if underlying_id is None:
            update_cols.pop("underlying_instrument_id", None)
        update_cols["updated_at"] = func.now()

        stmt = (
            pg_insert(Instrument)
            .values(**values)
            .on_conflict_do_update(constraint="uq_instruments_symbol", set_=update_cols)
            .returning(Instrument)
        )
        m = (await self._session.execute(stmt)).scalar_one()
        return _to_row(m)

    async def bulk_upsert(self, specs: list[InstrumentUpsert]) -> int:
        """Upsert many instruments. Returns the number of rows affected."""
        count = 0
        for spec in specs:
            await self.upsert(spec)
            count += 1
        return count

    async def list_active(self, instrument_type: str | None = None) -> list[InstrumentRow]:
        stmt = select(Instrument).where(Instrument.is_active.is_(True))
        if instrument_type is not None:
            stmt = stmt.where(Instrument.instrument_type == instrument_type.strip().upper())
        stmt = stmt.order_by(Instrument.symbol)
        return [_to_row(m) for m in (await self._session.execute(stmt)).scalars().all()]
