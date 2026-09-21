"""instrument_fundamentals: serve fundamentals from Postgres, not from the request path

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-21

Production (Railway, AS400940 / Amsterdam) receives HTTP 403 on Vietcap's VCI GraphQL
fundamentals query. The same library version, the same query and the same account succeed
from a US university network (AS11231) and from a GitHub-hosted runner (Azure, AS8075),
and Vietcap answers 200 to a bare POST on that host from Railway - so the rejection is
tied to the calling ASN for that query, and no code change in this repository can move
Railway's egress.

The effect on the API was total: `/api/market/fundamentals/{symbol}` returned pe, pb, eps,
roe and roa all null for every equity, with `quarters: []`, because the fetch raised before
anything was cached and nothing negative-cached the rejection either.

This table decouples the two. A scheduled job running on an egress that can reach Vietcap
writes here; the API reads here. Fundamentals change once a quarter, so nothing is lost by
not fetching them on a request.

Additive and reversible: a new table only, no change to any existing one.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "instrument_fundamentals",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        # Stored as the provider returned them: both payloads carry the per-field
        # provenance (`ratio_source`, `statement_source`, `period`) that the fundamentals
        # endpoint is required to report, and typed columns would drop it.
        sa.Column(
            "valuation", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "quarters", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column("source", sa.String(length=32), nullable=False),
        # The moment the ingestion reached the provider - the age the API reports.
        sa.Column(
            "observed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol", name="uq_instrument_fundamentals_symbol"),
    )


def downgrade() -> None:
    op.drop_table("instrument_fundamentals")
