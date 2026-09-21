"""Read/write access to `instrument_fundamentals`.

The request path only ever READS here. Writing is the scheduled ingestion's job, because
production cannot reach Vietcap's fundamentals endpoint at all: Railway's egress
(AS400940) is answered with HTTP 403 on the VCI GraphQL query while the identical library
version and query succeed from a university network (AS11231) and from a GitHub-hosted
runner (Azure, AS8075). Keeping the two directions in one module keeps the row shape
honest - whatever the ingestion stores is exactly what the API serves back.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.persistence.models import InstrumentFundamentals


async def get_fundamentals(
    session: AsyncSession, symbol: str
) -> InstrumentFundamentals | None:
    stmt = select(InstrumentFundamentals).where(
        InstrumentFundamentals.symbol == symbol.strip().upper()
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_many_fundamentals(
    session: AsyncSession, symbols: list[str]
) -> dict[str, InstrumentFundamentals]:
    clean = sorted({s.strip().upper() for s in symbols if s and s.strip()})
    if not clean:
        return {}
    stmt = select(InstrumentFundamentals).where(InstrumentFundamentals.symbol.in_(clean))
    return {row.symbol: row for row in (await session.execute(stmt)).scalars().all()}


async def upsert_fundamentals(
    session: AsyncSession,
    *,
    symbol: str,
    valuation: dict[str, Any],
    quarters: list[dict[str, Any]],
    source: str,
    observed_at: datetime | None = None,
) -> None:
    """Replace one symbol's fundamentals.

    A fetch that produced nothing must never land here - an empty row would be
    indistinguishable from a genuinely empty company and would overwrite a good previous
    answer with nulls, which is the failure this whole table exists to end. The caller
    (`app.persistence.cli fundamentals`) drops empty results before calling.
    """
    sym = symbol.strip().upper()
    observed = observed_at or datetime.now(timezone.utc)
    stmt = pg_insert(InstrumentFundamentals).values(
        symbol=sym,
        valuation=valuation or {},
        quarters=quarters or [],
        source=source,
        observed_at=observed,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_instrument_fundamentals_symbol",
        set_={
            "valuation": stmt.excluded.valuation,
            "quarters": stmt.excluded.quarters,
            "source": stmt.excluded.source,
            "observed_at": stmt.excluded.observed_at,
            "updated_at": datetime.now(timezone.utc),
        },
    )
    await session.execute(stmt)
