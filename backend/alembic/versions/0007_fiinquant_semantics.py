"""Preserve FiinQuant field semantics and per-group observation times.

Revision ID: 0007
Revises: 0006
"""

from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("market_bars", sa.Column("trading_value", sa.Numeric(24, 4), nullable=True))
    op.add_column("instrument_snapshots", sa.Column("ceiling_price", sa.Numeric(20, 4), nullable=True))
    op.add_column("instrument_snapshots", sa.Column("floor_price", sa.Numeric(20, 4), nullable=True))
    op.add_column("instrument_snapshots", sa.Column("traded_quantity", sa.BigInteger(), nullable=True))
    op.add_column("instrument_snapshots", sa.Column("trade_timestamp", sa.DateTime(timezone=True), nullable=True))
    op.add_column("instrument_snapshots", sa.Column("book_timestamp", sa.DateTime(timezone=True), nullable=True))
    op.add_column("instrument_snapshots", sa.Column("reference_timestamp", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("instrument_snapshots", "reference_timestamp")
    op.drop_column("instrument_snapshots", "book_timestamp")
    op.drop_column("instrument_snapshots", "trade_timestamp")
    op.drop_column("instrument_snapshots", "traded_quantity")
    op.drop_column("instrument_snapshots", "floor_price")
    op.drop_column("instrument_snapshots", "ceiling_price")
    op.drop_column("market_bars", "trading_value")
