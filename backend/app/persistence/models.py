"""SQLAlchemy 2.0 ORM models for the durable historical market-data store.

Schema summary
--------------
instruments      canonical instrument identity + relationships (NOT the rich CW terms,
                 which stay in the instrument registry snapshot)
market_bars      OHLCV bars, one logical row per (instrument, timeframe, open-time, basis)
ingestion_runs   one row per backfill/sync job, for observability
ingestion_state  incremental-sync cursor per (source, instrument, timeframe, basis)

All timestamp columns are ``timestamptz``. See ``app.persistence.market_time`` for the
timezone / bar-timestamp conventions.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


_TIMEFRAME_CHECK = "timeframe IN ('1m','5m','15m','30m','1h','1d')"
_PRICE_BASIS_CHECK = "price_basis IN ('ADJUSTED','RAW')"
_INSTRUMENT_TYPE_CHECK = "instrument_type IN ('CW','STOCK','INDEX')"
_RUN_STATUS_CHECK = "status IN ('RUNNING','SUCCEEDED','FAILED','PARTIAL')"


class Instrument(Base):
    __tablename__ = "instruments"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    instrument_type: Mapped[str] = mapped_column(String(16), nullable=False)
    exchange: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'HOSE'"))
    currency: Mapped[str] = mapped_column(String(8), nullable=False, server_default=text("'VND'"))

    # Underlying relationship (CW -> its underlying equity). Nullable: the underlying row
    # may not exist yet when a CW is first inserted.
    underlying_instrument_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("instruments.id", ondelete="SET NULL"), nullable=True
    )

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    first_trade_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_trade_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Small provenance pointer only (e.g. {"registry_snapshot": "...", "issuer": "SSI"}).
    # NOT a copy of the full instrument-registry record. Named ``attributes`` (not
    # ``metadata``) to avoid colliding with SQLAlchemy's ``DeclarativeBase.metadata``.
    attributes: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    underlying: Mapped["Instrument | None"] = relationship(remote_side=[id])
    bars: Mapped[list["MarketBar"]] = relationship(back_populates="instrument", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("symbol", name="uq_instruments_symbol"),
        CheckConstraint(_INSTRUMENT_TYPE_CHECK, name="ck_instruments_type"),
        Index("ix_instruments_type_active", "instrument_type", "is_active"),
    )


class MarketBar(Base):
    __tablename__ = "market_bars"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    instrument_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False
    )
    timeframe: Mapped[str] = mapped_column(String(4), nullable=False)
    # Bar OPEN instant, UTC. See app.persistence.market_time.
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Vietnam trading-session calendar date. Use this for calendar reasoning, never DATE(ts).
    session_date: Mapped[date] = mapped_column(Date, nullable=False)
    price_basis: Mapped[str] = mapped_column(String(8), nullable=False)

    open: Mapped[float] = mapped_column(Numeric(20, 4), nullable=False)
    high: Mapped[float] = mapped_column(Numeric(20, 4), nullable=False)
    low: Mapped[float] = mapped_column(Numeric(20, 4), nullable=False)
    close: Mapped[float] = mapped_column(Numeric(20, 4), nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))

    source: Mapped[str] = mapped_column(String(32), nullable=False)
    ingestion_run_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("ingestion_runs.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    instrument: Mapped["Instrument"] = relationship(back_populates="bars")

    __table_args__ = (
        # THE idempotency anchor + the index that serves latest-bar and range queries.
        UniqueConstraint(
            "instrument_id", "timeframe", "ts", "price_basis",
            name="uq_market_bars_identity",
        ),
        CheckConstraint(_TIMEFRAME_CHECK, name="ck_market_bars_timeframe"),
        CheckConstraint(_PRICE_BASIS_CHECK, name="ck_market_bars_price_basis"),
        CheckConstraint("high >= low", name="ck_market_bars_high_low"),
    )


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(4), nullable=False)
    price_basis: Mapped[str] = mapped_column(String(8), nullable=False)

    requested_symbols: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    requested_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    requested_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    status: Mapped[str] = mapped_column(String(12), nullable=False, server_default=text("'RUNNING'"))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    rows_fetched: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    rows_inserted: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    rows_updated: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    error_summary: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(_RUN_STATUS_CHECK, name="ck_ingestion_runs_status"),
        CheckConstraint(_TIMEFRAME_CHECK, name="ck_ingestion_runs_timeframe"),
        CheckConstraint(_PRICE_BASIS_CHECK, name="ck_ingestion_runs_price_basis"),
        Index("ix_ingestion_runs_status_started", "status", "started_at"),
    )


class IngestionState(Base):
    __tablename__ = "ingestion_state"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    instrument_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False
    )
    timeframe: Mapped[str] = mapped_column(String(4), nullable=False)
    price_basis: Mapped[str] = mapped_column(String(8), nullable=False)

    # Newest bar OPEN-time successfully persisted for this key (advisory cursor; the bars
    # table remains the source of truth for actual coverage).
    last_bar_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Oldest bar OPEN-time we have deliberately backfilled to.
    backfilled_from_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("ingestion_runs.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "source", "instrument_id", "timeframe", "price_basis",
            name="uq_ingestion_state_key",
        ),
        CheckConstraint(_TIMEFRAME_CHECK, name="ck_ingestion_state_timeframe"),
        CheckConstraint(_PRICE_BASIS_CHECK, name="ck_ingestion_state_price_basis"),
    )
