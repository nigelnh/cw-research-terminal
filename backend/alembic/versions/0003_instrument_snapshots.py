"""last-valid market snapshot per (symbol, session) — Step 13C after-hours fallback

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-29

Creates: instrument_snapshots.

One upserted row per symbol per VN trading session. Written by a throttled realtime
checkpoint task and once at the 15:00 ICT close / on graceful shutdown. This is the only
durable source for an after-hours closing bid/ask (FiinQuant serves no historical order
book) and the crash/redeploy recovery path for the current session's state. See
app.persistence.models.InstrumentSnapshot for the authoritative definition.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "instrument_snapshots",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=24), nullable=False),
        sa.Column("quality", sa.String(length=24), nullable=False),
        sa.Column("instrument_type", sa.String(length=8), nullable=False),
        sa.Column("reference_price", sa.Numeric(20, 4), nullable=True),
        sa.Column("last_price", sa.Numeric(20, 4), nullable=True),
        sa.Column("price_change", sa.Numeric(20, 4), nullable=True),
        sa.Column("price_change_percent", sa.Numeric(20, 8), nullable=True),
        sa.Column("open_price", sa.Numeric(20, 4), nullable=True),
        sa.Column("high_price", sa.Numeric(20, 4), nullable=True),
        sa.Column("low_price", sa.Numeric(20, 4), nullable=True),
        sa.Column("average_price", sa.Numeric(20, 4), nullable=True),
        sa.Column("total_volume", sa.BigInteger(), nullable=True),
        sa.Column("trading_value", sa.Numeric(24, 4), nullable=True),
        sa.Column("bid1_price", sa.Numeric(20, 4), nullable=True),
        sa.Column("bid1_quantity", sa.BigInteger(), nullable=True),
        sa.Column("ask1_price", sa.Numeric(20, 4), nullable=True),
        sa.Column("ask1_quantity", sa.BigInteger(), nullable=True),
        sa.Column("bid2_price", sa.Numeric(20, 4), nullable=True),
        sa.Column("bid2_quantity", sa.BigInteger(), nullable=True),
        sa.Column("ask2_price", sa.Numeric(20, 4), nullable=True),
        sa.Column("ask2_quantity", sa.BigInteger(), nullable=True),
        sa.Column("bid3_price", sa.Numeric(20, 4), nullable=True),
        sa.Column("bid3_quantity", sa.BigInteger(), nullable=True),
        sa.Column("ask3_price", sa.Numeric(20, 4), nullable=True),
        sa.Column("ask3_quantity", sa.BigInteger(), nullable=True),
        sa.Column("underlying_symbol", sa.String(length=32), nullable=True),
        sa.Column("underlying_price", sa.Numeric(20, 4), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("symbol", "session_date", name="uq_instrument_snapshots_symbol_session"),
        sa.CheckConstraint(
            "source IN ('REALTIME_CHECKPOINT','SESSION_CLOSE','HISTORICAL_SEED')",
            name="ck_instrument_snapshots_source",
        ),
        sa.CheckConstraint(
            "quality IN ('FINAL','INTRADAY_CHECKPOINT','SEED')",
            name="ck_instrument_snapshots_quality",
        ),
        sa.CheckConstraint(
            "instrument_type IN ('CW','STOCK','INDEX')",
            name="ck_instrument_snapshots_type",
        ),
    )
    op.create_index(
        "ix_instrument_snapshots_symbol_session",
        "instrument_snapshots",
        ["symbol", "session_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_instrument_snapshots_symbol_session", table_name="instrument_snapshots")
    op.drop_table("instrument_snapshots")
