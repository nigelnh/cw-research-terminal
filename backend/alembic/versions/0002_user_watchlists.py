"""user-owned primary watchlist (Step 9 authentication)

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-28

Creates: user_watchlists, user_watchlist_items.

Ownership key is the verified Supabase JWT ``sub`` stored as an opaque string. There is
deliberately NO foreign key into Supabase's auth schema - this PostgreSQL database is not
the Supabase database. See app.persistence.models for the authoritative definitions.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ITEM_TYPE_CHECK = "instrument_type IN ('CW','STOCK','INDEX')"


def upgrade() -> None:
    op.create_table(
        "user_watchlists",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("owner_subject", sa.String(length=255), nullable=False),
        sa.Column(
            "name", sa.String(length=120), nullable=False,
            server_default=sa.text("'Primary Watchlist'"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        # exactly one primary watchlist per owner; also the owner-lookup index
        sa.UniqueConstraint("owner_subject", name="uq_user_watchlists_owner"),
    )

    op.create_table(
        "user_watchlist_items",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("watchlist_id", sa.BigInteger(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("instrument_type", sa.String(length=16), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("underlying_symbol", sa.String(length=32), nullable=True),
        sa.Column("issuer", sa.String(length=64), nullable=True),
        sa.Column("strike_price", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("exercise_ratio", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column("maturity_date", sa.Date(), nullable=True),
        sa.Column("last_trading_date", sa.Date(), nullable=True),
        sa.Column("notes", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["watchlist_id"], ["user_watchlists.id"],
            name="fk_user_watchlist_items_watchlist", ondelete="CASCADE",
        ),
        sa.UniqueConstraint("watchlist_id", "symbol", name="uq_user_watchlist_items_symbol"),
        sa.UniqueConstraint("watchlist_id", "position", name="uq_user_watchlist_items_position"),
        sa.CheckConstraint(_ITEM_TYPE_CHECK, name="ck_user_watchlist_items_type"),
        sa.CheckConstraint("position >= 0", name="ck_user_watchlist_items_position"),
    )
    op.create_index(
        "ix_user_watchlist_items_watchlist", "user_watchlist_items", ["watchlist_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_user_watchlist_items_watchlist", table_name="user_watchlist_items")
    op.drop_table("user_watchlist_items")
    op.drop_table("user_watchlists")
