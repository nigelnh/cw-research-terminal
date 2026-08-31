"""generalise corporate_actions -> company_events; extend external_news for the unified feed (Step 14B)

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-31

`corporate_actions` is renamed to `company_events` and generalised so it can also hold
SSI financial-statement disclosures and insider / major-holder transactions — company
events that are NOT price-adjustment corporate actions. `event_class` is the discriminator.

This migration is a rename + column add + constraint swap + in-place backfill. Postgres
`ALTER TABLE RENAME` is transactional and instant; no data is copied or dropped, so the
change is fully reversible via downgrade().
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_TYPE_CK = (
    "event_type IN ('CASH_DIVIDEND','STOCK_DIVIDEND','BONUS_ISSUE','RIGHTS_ISSUE',"
    "'AGM','EGM','LISTING','DELISTING','ADDITIONAL_LISTING','FINANCIAL_STATEMENT',"
    "'INSIDER_TRANSACTION','OTHER')"
)
_CLASS_CK = (
    "event_class IN ('DIVIDEND','RIGHTS','MEETING','LISTING','FINANCIAL','OWNERSHIP','OTHER')"
)


def upgrade() -> None:
    # ---- external_news: add content_type for the unified feed ----
    op.add_column(
        "external_news",
        sa.Column(
            "content_type", sa.String(length=24), nullable=False,
            server_default=sa.text("'exchange_disclosure'"),
        ),
    )
    op.create_index(
        "ix_external_news_feed", "external_news", ["published_at", "id"],
        postgresql_using="btree",
    )
    # One label for the exchange: HSX (14A) and HOSE are the same venue.
    op.execute("UPDATE external_news SET source = 'HOSE' WHERE source = 'HSX'")

    # ---- corporate_actions -> company_events ----
    op.rename_table("corporate_actions", "company_events")
    op.alter_column("company_events", "action_type", new_column_name="event_type")
    op.alter_column("company_events", "event_type", type_=sa.String(length=24))
    op.alter_column("company_events", "note", type_=sa.String(length=2000))
    op.alter_column("company_events", "source_id", type_=sa.String(length=80))

    op.add_column(
        "company_events",
        sa.Column("event_class", sa.String(length=12), nullable=False, server_default=sa.text("'OTHER'")),
    )
    op.add_column("company_events", sa.Column("event_name", sa.String(length=200), nullable=True))
    op.add_column("company_events", sa.Column("source_event_code", sa.String(length=40), nullable=True))
    op.add_column("company_events", sa.Column("public_date", sa.Date(), nullable=True))
    op.add_column("company_events", sa.Column("value_text", sa.String(length=120), nullable=True))

    # backfill event_class from the existing event_type vocabulary
    op.execute(
        """
        UPDATE company_events SET event_class = CASE
          WHEN event_type IN ('CASH_DIVIDEND','STOCK_DIVIDEND','BONUS_ISSUE') THEN 'DIVIDEND'
          WHEN event_type = 'RIGHTS_ISSUE' THEN 'RIGHTS'
          WHEN event_type IN ('AGM','EGM') THEN 'MEETING'
          WHEN event_type IN ('LISTING','DELISTING') THEN 'LISTING'
          ELSE 'OTHER'
        END
        """
    )
    # public_date seed = disclosure_date where present (SSI rows will set it explicitly)
    op.execute("UPDATE company_events SET public_date = disclosure_date WHERE public_date IS NULL")

    # swap constraints
    op.drop_constraint("ck_corporate_actions_type", "company_events", type_="check")
    op.drop_constraint("ck_corporate_actions_status", "company_events", type_="check")
    op.drop_constraint("uq_corporate_actions_identity", "company_events", type_="unique")
    op.drop_index("ix_corporate_actions_symbol_ex", table_name="company_events")

    op.create_unique_constraint("uq_company_events_identity", "company_events", ["source", "source_id"])
    op.create_check_constraint("ck_company_events_type", "company_events", _NEW_TYPE_CK)
    op.create_check_constraint("ck_company_events_class", "company_events", _CLASS_CK)
    op.create_check_constraint(
        "ck_company_events_status", "company_events",
        "status IN ('SCHEDULED','CONFIRMED','CANCELLED','UNKNOWN')",
    )
    op.create_index("ix_company_events_symbol_ex", "company_events", ["symbol", "ex_date"])
    op.create_index("ix_company_events_symbol_class", "company_events", ["symbol", "event_class"])
    op.create_index("ix_company_events_sort", "company_events", ["public_date", "ex_date"])

    # ---- source_fetch_log: window + coverage tracking for the historical crawlers ----
    op.add_column("source_fetch_log", sa.Column("window_start", sa.Date(), nullable=True))
    op.add_column("source_fetch_log", sa.Column("window_end", sa.Date(), nullable=True))
    op.add_column("source_fetch_log", sa.Column("page", sa.Integer(), nullable=True))
    op.add_column("source_fetch_log", sa.Column("inserted", sa.Integer(), nullable=True))
    op.add_column("source_fetch_log", sa.Column("updated", sa.Integer(), nullable=True))
    op.add_column("source_fetch_log", sa.Column("complete", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("source_fetch_log", "complete")
    op.drop_column("source_fetch_log", "updated")
    op.drop_column("source_fetch_log", "inserted")
    op.drop_column("source_fetch_log", "page")
    op.drop_column("source_fetch_log", "window_end")
    op.drop_column("source_fetch_log", "window_start")

    op.drop_index("ix_company_events_sort", table_name="company_events")
    op.drop_index("ix_company_events_symbol_class", table_name="company_events")
    op.drop_index("ix_company_events_symbol_ex", table_name="company_events")
    op.drop_constraint("ck_company_events_status", "company_events", type_="check")
    op.drop_constraint("ck_company_events_class", "company_events", type_="check")
    op.drop_constraint("ck_company_events_type", "company_events", type_="check")
    op.drop_constraint("uq_company_events_identity", "company_events", type_="unique")

    op.execute("DELETE FROM company_events WHERE event_type IN ('FINANCIAL_STATEMENT','INSIDER_TRANSACTION','ADDITIONAL_LISTING')")
    op.drop_column("company_events", "value_text")
    op.drop_column("company_events", "public_date")
    op.drop_column("company_events", "source_event_code")
    op.drop_column("company_events", "event_name")
    op.drop_column("company_events", "event_class")

    op.alter_column("company_events", "source_id", type_=sa.String(length=80))
    op.alter_column("company_events", "note", type_=sa.String(length=1000))
    op.alter_column("company_events", "event_type", type_=sa.String(length=20))
    op.alter_column("company_events", "event_type", new_column_name="action_type")
    op.rename_table("company_events", "corporate_actions")

    op.create_unique_constraint("uq_corporate_actions_identity", "corporate_actions", ["source", "source_id"])
    op.create_check_constraint(
        "ck_corporate_actions_type", "corporate_actions",
        "action_type IN ('CASH_DIVIDEND','STOCK_DIVIDEND','BONUS_ISSUE','RIGHTS_ISSUE',"
        "'AGM','EGM','LISTING','DELISTING','OTHER')",
    )
    op.create_check_constraint(
        "ck_corporate_actions_status", "corporate_actions",
        "status IN ('SCHEDULED','CONFIRMED','CANCELLED','UNKNOWN')",
    )
    op.create_index("ix_corporate_actions_symbol_ex", "corporate_actions", ["symbol", "ex_date"])

    op.execute("UPDATE external_news SET source = 'HSX' WHERE source = 'HOSE'")
    op.drop_index("ix_external_news_feed", table_name="external_news")
    op.drop_column("external_news", "content_type")
