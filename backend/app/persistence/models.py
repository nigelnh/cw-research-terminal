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
    Integer,
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
_WATCHLIST_ITEM_TYPE_CHECK = "instrument_type IN ('CW','STOCK','INDEX')"


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

    underlying: Mapped[Instrument | None] = relationship(remote_side=[id])
    bars: Mapped[list[MarketBar]] = relationship(back_populates="instrument", cascade="all, delete-orphan")

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

    instrument: Mapped[Instrument] = relationship(back_populates="bars")

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


class InstrumentSnapshot(Base):
    """Last-valid realtime market snapshot per (symbol, trading session) — Step 13C.

    Written by a throttled checkpoint task during an active session and once at the 15:00
    ICT close / on graceful shutdown. This is the *only* durable source for an after-hours
    closing bid/ask (FiinQuant serves no historical order book) and the crash/redeploy
    recovery path for the current session's state. One upserted row per symbol per session.
    """

    __tablename__ = "instrument_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    # VN trading-session date this snapshot represents. Calendar reasoning uses this.
    session_date: Mapped[date] = mapped_column(Date, nullable=False)
    # Last observed instant folded into this row.
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(24), nullable=False)   # REALTIME_CHECKPOINT | SESSION_CLOSE | HISTORICAL_SEED
    quality: Mapped[str] = mapped_column(String(24), nullable=False)  # FINAL | INTRADAY_CHECKPOINT | SEED
    instrument_type: Mapped[str] = mapped_column(String(8), nullable=False)

    reference_price: Mapped[float | None] = mapped_column(Numeric(20, 4), nullable=True)
    last_price: Mapped[float | None] = mapped_column(Numeric(20, 4), nullable=True)
    price_change: Mapped[float | None] = mapped_column(Numeric(20, 4), nullable=True)
    price_change_percent: Mapped[float | None] = mapped_column(Numeric(20, 8), nullable=True)
    open_price: Mapped[float | None] = mapped_column(Numeric(20, 4), nullable=True)
    high_price: Mapped[float | None] = mapped_column(Numeric(20, 4), nullable=True)
    low_price: Mapped[float | None] = mapped_column(Numeric(20, 4), nullable=True)
    average_price: Mapped[float | None] = mapped_column(Numeric(20, 4), nullable=True)
    total_volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    trading_value: Mapped[float | None] = mapped_column(Numeric(24, 4), nullable=True)

    bid1_price: Mapped[float | None] = mapped_column(Numeric(20, 4), nullable=True)
    bid1_quantity: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    ask1_price: Mapped[float | None] = mapped_column(Numeric(20, 4), nullable=True)
    ask1_quantity: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    bid2_price: Mapped[float | None] = mapped_column(Numeric(20, 4), nullable=True)
    bid2_quantity: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    ask2_price: Mapped[float | None] = mapped_column(Numeric(20, 4), nullable=True)
    ask2_quantity: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    bid3_price: Mapped[float | None] = mapped_column(Numeric(20, 4), nullable=True)
    bid3_quantity: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    ask3_price: Mapped[float | None] = mapped_column(Numeric(20, 4), nullable=True)
    ask3_quantity: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    underlying_symbol: Mapped[str | None] = mapped_column(String(32), nullable=True)
    underlying_price: Mapped[float | None] = mapped_column(Numeric(20, 4), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("symbol", "session_date", name="uq_instrument_snapshots_symbol_session"),
        CheckConstraint(
            "source IN ('REALTIME_CHECKPOINT','SESSION_CLOSE','HISTORICAL_SEED')",
            name="ck_instrument_snapshots_source",
        ),
        CheckConstraint(
            "quality IN ('FINAL','INTRADAY_CHECKPOINT','SEED')",
            name="ck_instrument_snapshots_quality",
        ),
        CheckConstraint(_INSTRUMENT_TYPE_CHECK, name="ck_instrument_snapshots_type"),
        Index("ix_instrument_snapshots_symbol_session", "symbol", "session_date"),
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


# --------------------------------------------------------------------------- #
# User-owned data (Step 9). Ownership key = the verified Supabase JWT ``sub``. #
# This schema is deliberately standalone: it holds the auth subject as an      #
# opaque string and has NO foreign key into Supabase's internal auth tables    #
# (PostgreSQL here is not the Supabase database).                              #
# --------------------------------------------------------------------------- #
class UserWatchlist(Base):
    """One row per user - their single primary watchlist. (Not a multi-list abstraction:
    ``name`` is cosmetic and the ``owner_subject`` unique constraint enforces exactly one.)"""

    __tablename__ = "user_watchlists"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    # Verified JWT ``sub``. Opaque, immutable per Supabase user. Never sourced from a request body.
    owner_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(
        String(120), nullable=False, server_default=text("'Primary Watchlist'")
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    items: Mapped[list[UserWatchlistItem]] = relationship(
        back_populates="watchlist",
        cascade="all, delete-orphan",
        order_by="UserWatchlistItem.position",
        lazy="selectin",
    )

    __table_args__ = (
        # Exactly one primary watchlist per owner. Also serves as the owner lookup index.
        UniqueConstraint("owner_subject", name="uq_user_watchlists_owner"),
    )


class UserWatchlistItem(Base):
    __tablename__ = "user_watchlist_items"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    watchlist_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_watchlists.id", ondelete="CASCADE"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    instrument_type: Mapped[str] = mapped_column(String(16), nullable=False)
    # Dense 0-based rank. Deterministic ordering is (position ASC, id ASC).
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    underlying_symbol: Mapped[str | None] = mapped_column(String(32), nullable=True)
    issuer: Mapped[str | None] = mapped_column(String(64), nullable=True)
    strike_price: Mapped[float | None] = mapped_column(Numeric(20, 4), nullable=True)
    exercise_ratio: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    maturity_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_trading_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    watchlist: Mapped[UserWatchlist] = relationship(back_populates="items")

    __table_args__ = (
        UniqueConstraint("watchlist_id", "symbol", name="uq_user_watchlist_items_symbol"),
        UniqueConstraint("watchlist_id", "position", name="uq_user_watchlist_items_position"),
        CheckConstraint(_WATCHLIST_ITEM_TYPE_CHECK, name="ck_user_watchlist_items_type"),
        CheckConstraint("position >= 0", name="ck_user_watchlist_items_position"),
        Index("ix_user_watchlist_items_watchlist", "watchlist_id"),
    )


# --------------------------------------------------------------------------- #
# Step 14A — research data enrichment. Supplementary reference domains fed by  #
# controlled backend ingestion from public exchange / broker APIs. Every row  #
# is auditable (source + source_id + timestamps + raw). Read APIs over these  #
# tables NEVER touch an upstream source. A source failure here cannot affect  #
# /healthz, realtime, quant, or the core market APIs.                         #
# --------------------------------------------------------------------------- #
_CORPORATE_ACTION_TYPE_CHECK = (
    "action_type IN ('CASH_DIVIDEND','STOCK_DIVIDEND','BONUS_ISSUE','RIGHTS_ISSUE',"
    "'AGM','EGM','LISTING','DELISTING','OTHER')"
)
_CORPORATE_ACTION_STATUS_CHECK = "status IN ('SCHEDULED','CONFIRMED','CANCELLED','UNKNOWN')"


class ExternalNews(Base):
    """Exchange news / disclosure headlines (HSX). Incremental, deduplicated on
    ``(source, source_id)``. Symbol linkage is derived from the HOSE title-prefix
    convention (``MSH: ...`` / ``VHM.ACBS.8M.112 ...``) and only when confident."""

    __tablename__ = "external_news"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    source: Mapped[str] = mapped_column(String(24), nullable=False)          # HSX
    source_id: Mapped[str] = mapped_column(String(64), nullable=False)       # upstream news id
    lang: Mapped[str] = mapped_column(String(4), nullable=False, server_default=text("'vi'"))

    title: Mapped[str] = mapped_column(String(1000), nullable=False)
    summary_html: Mapped[str | None] = mapped_column(String(8000), nullable=True)
    category: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Best-effort symbol linkage (list of tickers). Empty when we can't be sure.
    symbols: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    related_source_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    url: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    raw: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("source", "source_id", "lang", name="uq_external_news_identity"),
        Index("ix_external_news_published", "published_at"),
        Index("ix_external_news_symbols", "symbols", postgresql_using="gin"),
    )


class CorporateAction(Base):
    """Structured corporate-action events (VNDirect ``v4/events``). Deduplicated on
    ``(source, source_id)``. Cash amounts in VND/share; ``ratio_pct`` for share
    distributions. Contract/history adjustment logic consumes these read-only."""

    __tablename__ = "corporate_actions"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    source: Mapped[str] = mapped_column(String(24), nullable=False)          # VNDIRECT
    source_id: Mapped[str] = mapped_column(String(80), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)

    action_type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, server_default=text("'UNKNOWN'"))

    ex_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    record_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    payment_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    disclosure_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    cash_amount_vnd: Mapped[float | None] = mapped_column(Numeric(20, 4), nullable=True)
    ratio_pct: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)
    ratio_text: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dividend_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    url: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    raw: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("source", "source_id", name="uq_corporate_actions_identity"),
        CheckConstraint(_CORPORATE_ACTION_TYPE_CHECK, name="ck_corporate_actions_type"),
        CheckConstraint(_CORPORATE_ACTION_STATUS_CHECK, name="ck_corporate_actions_status"),
        Index("ix_corporate_actions_symbol_ex", "symbol", "ex_date"),
    )


class CompanyProfile(Base):
    """Underlying / listed-company reference data (VNDirect ``company_profiles``).
    One row per symbol. Reference only — never feeds quant or contract terms."""

    __tablename__ = "company_profiles"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    exchange: Mapped[str | None] = mapped_column(String(16), nullable=True)

    vn_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    en_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(200), nullable=True)
    found_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    tax_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    website: Mapped[str | None] = mapped_column(String(300), nullable=True)
    listed_shares: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    outstanding_shares: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    source: Mapped[str] = mapped_column(String(24), nullable=False)
    source_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    raw: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("symbol", name="uq_company_profiles_symbol"),
    )


class SourceFetchLog(Base):
    """One row per external HTTP fetch attempt against an enrichment source. Pure
    observability — bounded retention is a later concern."""

    __tablename__ = "source_fetch_log"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    source: Mapped[str] = mapped_column(String(24), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(120), nullable=False)
    symbol: Mapped[str | None] = mapped_column(String(32), nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    error: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_source_fetch_log_source_time", "source", "fetched_at"),
    )
