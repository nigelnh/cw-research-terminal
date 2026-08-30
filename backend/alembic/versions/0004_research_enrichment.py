"""research data enrichment — news, corporate actions, company reference, fetch log (Step 14A)

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-31

Creates: external_news, corporate_actions, company_profiles, source_fetch_log.

Supplementary reference domains populated by controlled backend ingestion from public
exchange / broker APIs (HSX news, VNDirect v4/events + company_profiles). Every row is
auditable via (source, source_id) + timestamps + a raw jsonb blob. Read APIs over these
tables never touch an upstream source. Additive-only; no changes to existing tables.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "external_news",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("source", sa.String(length=24), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("lang", sa.String(length=4), nullable=False, server_default=sa.text("'vi'")),
        sa.Column("title", sa.String(length=1000), nullable=False),
        sa.Column("summary_html", sa.String(length=8000), nullable=True),
        sa.Column("category", sa.String(length=200), nullable=True),
        sa.Column("symbols", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("related_source_id", sa.String(length=64), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("url", sa.String(length=1000), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("raw", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("source", "source_id", "lang", name="uq_external_news_identity"),
    )
    op.create_index("ix_external_news_published", "external_news", ["published_at"])
    op.create_index(
        "ix_external_news_symbols", "external_news", ["symbols"], postgresql_using="gin"
    )

    op.create_table(
        "corporate_actions",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("source", sa.String(length=24), nullable=False),
        sa.Column("source_id", sa.String(length=80), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("action_type", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False, server_default=sa.text("'UNKNOWN'")),
        sa.Column("ex_date", sa.Date(), nullable=True),
        sa.Column("record_date", sa.Date(), nullable=True),
        sa.Column("payment_date", sa.Date(), nullable=True),
        sa.Column("disclosure_date", sa.Date(), nullable=True),
        sa.Column("cash_amount_vnd", sa.Numeric(20, 4), nullable=True),
        sa.Column("ratio_pct", sa.Numeric(12, 6), nullable=True),
        sa.Column("ratio_text", sa.String(length=64), nullable=True),
        sa.Column("dividend_year", sa.Integer(), nullable=True),
        sa.Column("note", sa.String(length=1000), nullable=True),
        sa.Column("url", sa.String(length=1000), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("raw", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("source", "source_id", name="uq_corporate_actions_identity"),
        sa.CheckConstraint(
            "action_type IN ('CASH_DIVIDEND','STOCK_DIVIDEND','BONUS_ISSUE','RIGHTS_ISSUE',"
            "'AGM','EGM','LISTING','DELISTING','OTHER')",
            name="ck_corporate_actions_type",
        ),
        sa.CheckConstraint(
            "status IN ('SCHEDULED','CONFIRMED','CANCELLED','UNKNOWN')",
            name="ck_corporate_actions_status",
        ),
    )
    op.create_index("ix_corporate_actions_symbol_ex", "corporate_actions", ["symbol", "ex_date"])

    op.create_table(
        "company_profiles",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("exchange", sa.String(length=16), nullable=True),
        sa.Column("vn_name", sa.String(length=300), nullable=True),
        sa.Column("en_name", sa.String(length=300), nullable=True),
        sa.Column("industry", sa.String(length=200), nullable=True),
        sa.Column("found_date", sa.Date(), nullable=True),
        sa.Column("tax_code", sa.String(length=32), nullable=True),
        sa.Column("website", sa.String(length=300), nullable=True),
        sa.Column("listed_shares", sa.BigInteger(), nullable=True),
        sa.Column("outstanding_shares", sa.BigInteger(), nullable=True),
        sa.Column("source", sa.String(length=24), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("raw", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("symbol", name="uq_company_profiles_symbol"),
    )

    op.create_table(
        "source_fetch_log",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("source", sa.String(length=24), nullable=False),
        sa.Column("endpoint", sa.String(length=120), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("item_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("ok", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("error", sa.String(length=1000), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_source_fetch_log_source_time", "source_fetch_log", ["source", "fetched_at"])


def downgrade() -> None:
    op.drop_index("ix_source_fetch_log_source_time", table_name="source_fetch_log")
    op.drop_table("source_fetch_log")
    op.drop_table("company_profiles")
    op.drop_index("ix_corporate_actions_symbol_ex", table_name="corporate_actions")
    op.drop_table("corporate_actions")
    op.drop_index("ix_external_news_symbols", table_name="external_news")
    op.drop_index("ix_external_news_published", table_name="external_news")
    op.drop_table("external_news")
