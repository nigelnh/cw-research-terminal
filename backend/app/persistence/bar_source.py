"""``PostgresHistoricalBarSource`` - the persistence-backed ``HistoricalBarSource`` that
``HistoricalVolatilityService`` reads from once persistence is enabled (Step 7).

    PostgreSQL
      -> PostgresHistoricalBarSource.get_historical_bars()   (pure read)
      -> HistoricalVolatilityService.refresh() / warm()       (background, off the tick path)
      -> in-memory VolEstimate cache
      -> LiveQuantEngine.get_estimate()                        (pure in-memory)

Optional ``gap_filler``: if a symbol has fewer than ``min_bars_for_fill`` persisted daily
bars, a single controlled provider gap-fill is triggered (single-flighted, bounded,
NEVER on the per-tick path) and the read is retried against PostgreSQL. ``LiveQuantEngine``
never fetches from a provider directly.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.market_data.market_schemas import HistoricalBar
from app.persistence.ingestion.trading_calendar import last_completed_session_date
from app.persistence.market_time import VN_TZ, normalize_price_basis, normalize_timeframe
from app.persistence.repositories.market_bar_repository import MarketBarRepository

logger = logging.getLogger(__name__)


class GapFiller(Protocol):
    async def fill_range(
        self, symbol: str, *, timeframe: str, price_basis: str, from_date: date, to_date: date,
        lock_wait_seconds: float | None = ...,
    ) -> Any: ...


class PostgresHistoricalBarSource:
    """Reads persisted bars. Structurally compatible with ``FiinQuantProvider`` for the one
    method ``HistoricalVolatilityService`` calls."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        gap_filler: GapFiller | None = None,
        min_bars_for_fill: int = 0,
    ) -> None:
        self._session_factory = session_factory
        self._gap_filler = gap_filler
        self._min_bars_for_fill = int(min_bars_for_fill)

    async def get_historical_bars(
        self,
        symbol: str,
        timeframe: str = "1D",
        from_date: str | None = None,
        to_date: str | None = None,
        adjusted: bool = True,
    ) -> list[HistoricalBar]:
        tf = normalize_timeframe(timeframe)
        price_basis = normalize_price_basis(adjusted=adjusted)
        start = _vn_day_start_utc(from_date)
        end = _vn_day_start_utc(to_date, plus_days=1)

        rows = await self._read(symbol, tf, price_basis, start, end)

        if (
            len(rows) < self._min_bars_for_fill
            and self._gap_filler is not None
            and tf == "1d"
        ):
            fill_from = (
                _parse_date(from_date)
                or (date.today() - timedelta(days=settings.INGEST_MAX_LOOKBACK_DAYS))
            )
            fill_to = _parse_date(to_date) or last_completed_session_date()
            try:
                logger.info(
                    "HV source: %s has %d/%d bars; triggering controlled gap-fill %s..%s",
                    symbol.upper(), len(rows), self._min_bars_for_fill, fill_from, fill_to,
                )
                await self._gap_filler.fill_range(
                    symbol.upper(), timeframe="1d", price_basis=price_basis,
                    from_date=fill_from, to_date=fill_to,
                )
                rows = await self._read(symbol, tf, price_basis, start, end)
            except Exception as exc:  # noqa: BLE001 - a fill failure must not break HV refresh
                logger.warning("HV source gap-fill for %s failed: %s: %s", symbol, exc.__class__.__name__, exc)

        return [
            HistoricalBar(
                date=r.session_date.isoformat(),
                open=r.open, high=r.high, low=r.low, close=r.close,
                volume=float(r.volume), adjusted=(r.price_basis == "ADJUSTED"),
            )
            for r in rows
        ]

    async def _read(self, symbol: str, tf: str, price_basis: str, start, end):
        async with self._session_factory() as session:
            return await MarketBarRepository(session).get_bars(
                symbol=symbol, timeframe=tf, price_basis=price_basis,
                start=start, end=end, ascending=True,
            )


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    part = value.strip().replace("T", " ").split(" ")[0]
    y, m, d = (int(x) for x in part.split("-"))
    return date(y, m, d)


def _vn_day_start_utc(value: str | None, *, plus_days: int = 0) -> datetime | None:
    d = _parse_date(value)
    if d is None:
        return None
    return datetime.combine(d + timedelta(days=plus_days), time(0, 0), tzinfo=VN_TZ)
