"""Schema-level checks for the Step 9 user-owned tables + full model/migration drift guard."""

from __future__ import annotations

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.asyncio


async def test_user_watchlist_tables_exist(engine):
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
        )
        tables = {r[0] for r in rows}
    assert {"user_watchlists", "user_watchlist_items"} <= tables


async def test_ownership_and_ordering_constraints_exist(engine):
    async with engine.connect() as conn:
        rows = await conn.execute(text("SELECT conname FROM pg_constraint WHERE contype IN ('u','c')"))
        names = {r[0] for r in rows}
    assert "uq_user_watchlists_owner" in names          # one primary list per owner
    assert "uq_user_watchlist_items_symbol" in names    # no duplicate symbols
    assert "uq_user_watchlist_items_position" in names  # deterministic ordering
    assert "ck_user_watchlist_items_type" in names
    assert "ck_user_watchlist_items_position" in names


async def test_owner_subject_is_indexed(engine):
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT indexdef FROM pg_indexes WHERE tablename='user_watchlists'")
        )
        defs = " ".join(r[0] for r in rows)
    assert "owner_subject" in defs


async def test_models_and_migrations_do_not_drift(engine):
    """`alembic upgrade head` (run by the fixture) must produce a schema identical to the
    ORM models - no forgotten migration for any table, Step 9 included."""
    from alembic.autogenerate import compare_metadata
    from alembic.runtime.migration import MigrationContext

    from app.persistence.models import Base

    def _diff(sync_conn):
        ctx = MigrationContext.configure(
            sync_conn, opts={"compare_type": True, "target_metadata": Base.metadata}
        )
        return compare_metadata(ctx, Base.metadata)

    async with engine.connect() as conn:
        diffs = await conn.run_sync(_diff)
    assert diffs == [], f"model/migration drift detected: {diffs}"
