"""initial market-data persistence schema

Revision ID: 0001
Revises:
Create Date: 2026-08-27

Creates: instruments, ingestion_runs, market_bars, ingestion_state.
See app.persistence.models for the authoritative column/constraint definitions and
app.persistence.market_time for the timestamp conventions.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TIMEFRAME_CHECK = "timeframe IN ('1m','5m','15m','30m','1h','1d')"
_PRICE_BASIS_CHECK = "price_basis IN ('ADJUSTED','RAW')"


def upgrade() -> None:
    op.create_table(
        "instruments",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("instrument_type", sa.String(length=16), nullable=False),
        sa.Column("exchange", sa.String(length=16), nullable=False, server_default=sa.text("'HOSE'")),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default=sa.text("'VND'")),
        sa.Column("underlying_instrument_id", sa.BigInteger(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("first_trade_date", sa.Date(), nullable=True),
        sa.Column("last_trade_date", sa.Date(), nullable=True),
        sa.Column("attributes", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["underlying_instrument_id"], ["instruments.id"],
            name="fk_instruments_underlying", ondelete="SET NULL",
        ),
        sa.UniqueConstraint("symbol", name="uq_instruments_symbol"),
        sa.CheckConstraint("instrument_type IN ('CW','STOCK','INDEX')", name="ck_instruments_type"),
    )
    op.create_index("ix_instruments_type_active", "instruments", ["instrument_type", "is_active"])

    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("timeframe", sa.String(length=4), nullable=False),
        sa.Column("price_basis", sa.String(length=8), nullable=False),
        sa.Column("requested_symbols", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("requested_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requested_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=12), nullable=False, server_default=sa.text("'RUNNING'")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rows_fetched", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("rows_inserted", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("rows_updated", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("error_summary", sa.String(length=2000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('RUNNING','SUCCEEDED','FAILED','PARTIAL')", name="ck_ingestion_runs_status"),
        sa.CheckConstraint(_TIMEFRAME_CHECK, name="ck_ingestion_runs_timeframe"),
        sa.CheckConstraint(_PRICE_BASIS_CHECK, name="ck_ingestion_runs_price_basis"),
    )
    op.create_index("ix_ingestion_runs_status_started", "ingestion_runs", ["status", "started_at"])

    op.create_table(
        "market_bars",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("instrument_id", sa.BigInteger(), nullable=False),
        sa.Column("timeframe", sa.String(length=4), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("price_basis", sa.String(length=8), nullable=False),
        sa.Column("open", sa.Numeric(precision=20, scale=4), nullable=False),
        sa.Column("high", sa.Numeric(precision=20, scale=4), nullable=False),
        sa.Column("low", sa.Numeric(precision=20, scale=4), nullable=False),
        sa.Column("close", sa.Numeric(precision=20, scale=4), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("ingestion_run_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["instrument_id"], ["instruments.id"],
            name="fk_market_bars_instrument", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"], ["ingestion_runs.id"],
            name="fk_market_bars_run", ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "instrument_id", "timeframe", "ts", "price_basis", name="uq_market_bars_identity"
        ),
        sa.CheckConstraint(_TIMEFRAME_CHECK, name="ck_market_bars_timeframe"),
        sa.CheckConstraint(_PRICE_BASIS_CHECK, name="ck_market_bars_price_basis"),
        sa.CheckConstraint("high >= low", name="ck_market_bars_high_low"),
    )

    op.create_table(
        "ingestion_state",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("instrument_id", sa.BigInteger(), nullable=False),
        sa.Column("timeframe", sa.String(length=4), nullable=False),
        sa.Column("price_basis", sa.String(length=8), nullable=False),
        sa.Column("last_bar_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("backfilled_from_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["instrument_id"], ["instruments.id"],
            name="fk_ingestion_state_instrument", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["last_run_id"], ["ingestion_runs.id"],
            name="fk_ingestion_state_run", ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "source", "instrument_id", "timeframe", "price_basis", name="uq_ingestion_state_key"
        ),
        sa.CheckConstraint(_TIMEFRAME_CHECK, name="ck_ingestion_state_timeframe"),
        sa.CheckConstraint(_PRICE_BASIS_CHECK, name="ck_ingestion_state_price_basis"),
    )


def downgrade() -> None:
    op.drop_table("ingestion_state")
    op.drop_table("market_bars")
    op.drop_index("ix_ingestion_runs_status_started", table_name="ingestion_runs")
    op.drop_table("ingestion_runs")
    op.drop_index("ix_instruments_type_active", table_name="instruments")
    op.drop_table("instruments")
