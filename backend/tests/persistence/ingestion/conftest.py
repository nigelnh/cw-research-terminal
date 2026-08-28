"""Fixtures for historical-ingestion integration tests.

Reuses the disposable real-PostgreSQL cluster from ``tests/persistence/conftest.py``.
No real FiinQuant calls: a deterministic in-memory ``FakeHistoricalProvider`` stands in
for the provider and records every request.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import pytest
import pytest_asyncio

from app.market_data.market_schemas import HistoricalBar
from app.persistence.ingestion.service import IngestionService


@dataclass
class FakeHistoricalProvider:
    """In-memory OHLCV source.

    ``bars[symbol][iso_date] -> HistoricalBar``. ``get_historical_bars`` returns the bars
    whose date is within the inclusive request window. Hooks:
      * ``fail_symbol[symbol] = Exception``  -> always raised for that symbol
      * ``raise_on_call[n] = Exception``     -> raised on the n-th (0-based) call, once
    """

    bars: dict[str, dict[str, HistoricalBar]] = field(default_factory=dict)
    calls: list[tuple] = field(default_factory=list)
    fail_symbol: dict[str, Exception] = field(default_factory=dict)
    raise_on_call: dict[int, Exception] = field(default_factory=dict)

    def seed_daily(
        self, symbol: str, start: date, end: date, *, base: float = 100.0, step: float = 0.25,
        adjusted: bool = True, weekdays_only: bool = True,
    ) -> None:
        sym = symbol.upper()
        book = self.bars.setdefault(sym, {})
        px = base
        d = start
        while d <= end:
            if not weekdays_only or d.weekday() < 5:
                book[d.isoformat()] = HistoricalBar(
                    date=d.isoformat(), open=px, high=px + 1.0, low=px - 1.0, close=px + 0.5,
                    volume=1000 + int((px - base) * 10), adjusted=adjusted,
                )
                px += step
            d += timedelta(days=1)

    def revise_close(self, symbol: str, iso_date: str, new_close: float) -> None:
        b = self.bars[symbol.upper()][iso_date]
        self.bars[symbol.upper()][iso_date] = HistoricalBar(
            date=b.date, open=b.open, high=max(b.high, new_close), low=min(b.low, new_close),
            close=new_close, volume=b.volume, adjusted=b.adjusted,
        )

    async def get_historical_bars(
        self, symbol: str, timeframe: str = "1D", from_date: str | None = None,
        to_date: str | None = None, adjusted: bool = True,
    ) -> list[HistoricalBar]:
        n = len(self.calls)
        self.calls.append((symbol.upper(), timeframe, from_date, to_date, adjusted))
        if symbol.upper() in self.fail_symbol:
            raise self.fail_symbol[symbol.upper()]
        if n in self.raise_on_call:
            exc = self.raise_on_call.pop(n)
            raise exc
        book = self.bars.get(symbol.upper(), {})
        lo = date.fromisoformat(from_date) if from_date else date.min
        hi = date.fromisoformat(to_date) if to_date else date.max
        return [b for iso, b in sorted(book.items()) if lo <= date.fromisoformat(iso) <= hi]


@pytest_asyncio.fixture(autouse=True)
async def _configure_global_db(engine):
    """Point ``app.persistence.database`` (used by seed_instruments / session_scope) at the
    disposable test cluster for the duration of each ingestion test."""
    from app.persistence import database as db

    prev_engine = db._engine  # noqa: SLF001
    prev_sm = db._sessionmaker  # noqa: SLF001
    db.configure(engine)
    try:
        yield
    finally:
        db._engine = prev_engine  # noqa: SLF001
        db._sessionmaker = prev_sm  # noqa: SLF001


@pytest.fixture
def fake_provider() -> FakeHistoricalProvider:
    return FakeHistoricalProvider()


@pytest_asyncio.fixture
async def ingestion_service(engine, sessionmaker_, fake_provider, monkeypatch) -> IngestionService:
    from app.core.config import settings
    from app.persistence.ingestion.retry import RetryPolicy

    # tests must not eat the 2s production inter-request throttle
    monkeypatch.setattr(settings, "INGEST_MIN_REQUEST_INTERVAL_SECONDS", 0.0)
    return IngestionService(
        engine=engine,
        sessionmaker=sessionmaker_,
        bar_provider=fake_provider,
        source="fiinquant",
        retry_policy=RetryPolicy(max_retries=3, base_seconds=0.001, max_seconds=0.01),
    )


@pytest_asyncio.fixture
async def history_service(engine, sessionmaker_, fake_provider, ingestion_service, monkeypatch):
    """`history_read_service` singleton wired to the test cluster in postgres_first mode."""
    from app.core.config import settings
    from app.market_data.history_read_service import history_read_service

    monkeypatch.setattr(settings, "DATABASE_ENABLED", True)
    monkeypatch.setattr(settings, "HISTORY_SOURCE_MODE", "postgres_first")
    monkeypatch.setattr(settings, "HISTORY_GAPFILL_ENABLED", True)
    monkeypatch.setattr(settings, "HISTORY_GAPFILL_LOCK_WAIT_SECONDS", 10.0)

    history_read_service.configure(
        engine=engine, sessionmaker=sessionmaker_, provider=fake_provider,
        ingestion_service=ingestion_service,
    )
    # reset per-test counters / cooldowns
    for k in history_read_service._counters:  # noqa: SLF001
        history_read_service._counters[k] = 0
    history_read_service._fill_failure_until.clear()  # noqa: SLF001
    history_read_service._last_fill = None  # noqa: SLF001
    yield history_read_service
    history_read_service.reset()
    history_read_service.set_provider(None)
