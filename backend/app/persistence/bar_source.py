"""``PostgresHistoricalBarSource`` - a persistence-backed implementation of the
``HistoricalBarSource`` protocol that ``HistoricalVolatilityService`` consumes.

NOT wired into the application yet (Step 7). It exists here, tested, so the later swap is
a one-line change in ``app.main`` with zero changes to ``HistoricalVolatilityService`` or
``LiveQuantEngine``:

    # today
    historical_volatility_service.set_bar_source(subscription_manager.provider)   # FiinQuantProvider

    # Step 7
    historical_volatility_service.set_bar_source(
        PostgresHistoricalBarSource(get_sessionmaker())
    )

Both objects expose the same single coroutine ``get_historical_bars(...)`` returning
objects with a numeric ``.close`` attribute, which is all the service reads.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.market_data.market_schemas import HistoricalBar
from app.persistence.market_time import VN_TZ, normalize_price_basis, normalize_timeframe
from app.persistence.repositories.market_bar_repository import MarketBarRepository


class PostgresHistoricalBarSource:
    """Reads persisted bars. Structurally compatible with ``FiinQuantProvider`` for the
    one method ``HistoricalVolatilityService`` calls."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

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
        # from_date / to_date are Vietnam trading-session dates. Translate to a half-open
        # UTC window [from 00:00 VN, (to + 1 day) 00:00 VN) so the whole `to_date` session
        # is included and daily bars (whose ts is VN-midnight) line up.
        start = _vn_day_start_utc(from_date)
        end = _vn_day_start_utc(to_date, plus_days=1)

        async with self._session_factory() as session:
            repo = MarketBarRepository(session)
            rows = await repo.get_bars(
                symbol=symbol,
                timeframe=tf,
                price_basis=price_basis,
                start=start,
                end=end,
                ascending=True,
            )

        return [
            HistoricalBar(
                date=r.session_date.isoformat(),
                open=r.open,
                high=r.high,
                low=r.low,
                close=r.close,
                volume=float(r.volume),
                adjusted=(r.price_basis == "ADJUSTED"),
            )
            for r in rows
        ]


def _vn_day_start_utc(value: str | None, *, plus_days: int = 0) -> datetime | None:
    if not value:
        return None
    date_part = value.strip().replace("T", " ").split(" ")[0]
    y, m, d = (int(x) for x in date_part.split("-"))
    day = date(y, m, d) + timedelta(days=plus_days)
    return datetime.combine(day, time(0, 0), tzinfo=VN_TZ)
