"""drop external_news.raw — stop storing full HOSE payloads (post-incident storage fix)

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-31

A 24-month market-wide corpus of full HSX JSON payloads in ``external_news.raw``
exhausted the 434 MiB production Postgres volume and crashlooped the database.
HOSE is a public feed, re-fetchable by ``(source, source_id)`` and stable date
windows, so the full raw blob does not justify the storage. Normalized provenance
(source / source_id / lang / title / summary_html / symbols / category /
content_type / timestamps / url) is retained.

``ALTER TABLE ... DROP COLUMN`` is a catalog-only operation in PostgreSQL — no table
rewrite, minimal WAL — deliberately NOT a mass ``UPDATE ... SET raw = NULL`` (that
pattern generated ~60 MiB of avoidable WAL + dead tuples during the incident).

``company_events.raw`` is intentionally left in place: SSI payloads are ~1.5 MiB
total and materially useful for future event reclassification.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("external_news", "raw")


def downgrade() -> None:
    # Irreversible in content: the payloads are gone. Re-add the column with a default
    # so the schema round-trips; rows will carry '{}' until re-ingested.
    op.add_column(
        "external_news",
        sa.Column(
            "raw",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
