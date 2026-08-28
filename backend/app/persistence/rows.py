"""Plain, detached DTOs returned by the repository layer.

The repositories never leak SQLAlchemy ORM instances to application code - they return
these frozen dataclasses instead. That keeps the persistence boundary explicit and avoids
lazy-load / detached-instance surprises.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True, slots=True)
class InstrumentRow:
    id: int
    symbol: str
    instrument_type: str
    exchange: str
    currency: str
    underlying_instrument_id: int | None
    is_active: bool
    first_trade_date: date | None
    last_trade_date: date | None
    metadata: dict
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class BarRow:
    instrument_id: int
    timeframe: str
    ts: datetime          # bar OPEN instant, UTC
    session_date: date     # Vietnam trading-session date
    price_basis: str       # "ADJUSTED" | "RAW"
    open: float
    high: float
    low: float
    close: float
    volume: int
    source: str
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class BarUpsert:
    """One bar to persist. ``ts`` must be tz-aware; the repository normalizes to UTC and
    derives ``session_date`` if not supplied."""
    instrument_id: int
    timeframe: str
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    price_basis: str
    source: str
    session_date: date | None = None


@dataclass(frozen=True, slots=True)
class BarCoverage:
    instrument_id: int
    timeframe: str
    price_basis: str
    earliest_ts: datetime | None
    latest_ts: datetime | None
    bar_count: int


@dataclass(frozen=True, slots=True)
class UpsertResult:
    inserted: int
    updated: int

    @property
    def total(self) -> int:
        return self.inserted + self.updated


@dataclass(frozen=True, slots=True)
class IngestionRunRow:
    id: int
    source: str
    timeframe: str
    price_basis: str
    requested_symbols: list
    requested_from: datetime | None
    requested_to: datetime | None
    status: str
    started_at: datetime
    completed_at: datetime | None
    rows_fetched: int
    rows_inserted: int
    rows_updated: int
    error_summary: str | None


@dataclass(frozen=True, slots=True)
class UserWatchlistItemRow:
    symbol: str
    instrument_type: str
    position: int
    underlying_symbol: str | None
    issuer: str | None
    strike_price: float | None
    exercise_ratio: float | None
    maturity_date: date | None
    last_trading_date: date | None
    notes: str | None


@dataclass(frozen=True, slots=True)
class UserWatchlistRow:
    owner_subject: str
    name: str
    items: tuple[UserWatchlistItemRow, ...]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class IngestionStateRow:
    id: int
    source: str
    instrument_id: int
    timeframe: str
    price_basis: str
    last_bar_ts: datetime | None
    backfilled_from_ts: datetime | None
    last_success_at: datetime | None
    last_run_id: int | None
    updated_at: datetime
