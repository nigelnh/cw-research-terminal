"""Migration / schema-creation tests against a real PostgreSQL."""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.asyncio

_EXPECTED_TABLES = {"instruments", "market_bars", "ingestion_runs", "ingestion_state", "alembic_version"}
_EXPECTED_INDEXES = {
    "uq_instruments_symbol",
    "ix_instruments_type_active",
    "uq_market_bars_identity",
    "uq_ingestion_state_key",
    "ix_ingestion_runs_status_started",
}
_EXPECTED_CHECKS = {
    "ck_instruments_type",
    "ck_market_bars_timeframe",
    "ck_market_bars_price_basis",
    "ck_market_bars_high_low",
    "ck_ingestion_runs_status",
}


async def test_migration_created_all_tables(engine):
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
        )
        tables = {r[0] for r in rows}
    assert _EXPECTED_TABLES <= tables


async def test_expected_indexes_and_unique_constraints_exist(engine):
    async with engine.connect() as conn:
        rows = await conn.execute(text("SELECT indexname FROM pg_indexes WHERE schemaname='public'"))
        indexes = {r[0] for r in rows}
    missing = _EXPECTED_INDEXES - indexes
    assert not missing, f"missing indexes: {missing}"


async def test_check_constraints_exist(engine):
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT conname FROM pg_constraint WHERE contype='c' "
                "AND connamespace = 'public'::regnamespace"
            )
        )
        checks = {r[0] for r in rows}
    assert _EXPECTED_CHECKS <= checks


async def test_market_bars_numeric_precision_and_ts_are_timestamptz(engine):
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT column_name, data_type, numeric_precision, numeric_scale "
                "FROM information_schema.columns WHERE table_name='market_bars'"
            )
        )
        cols = {r[0]: (r[1], r[2], r[3]) for r in rows}
    assert cols["ts"][0] == "timestamp with time zone"
    assert cols["session_date"][0] == "date"
    for price_col in ("open", "high", "low", "close"):
        assert cols[price_col][0] == "numeric"
        assert cols[price_col][1] == 20 and cols[price_col][2] == 4
    assert cols["volume"][0] == "bigint"


async def test_downgrade_then_upgrade_roundtrips(pg_cluster):
    """`alembic downgrade base` drops everything; `upgrade head` rebuilds it."""
    from alembic import command
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", pg_cluster["alembic_cfg"].get_main_option("script_location"))
    prev = os.environ.get("ALEMBIC_DATABASE_URL")
    os.environ["ALEMBIC_DATABASE_URL"] = pg_cluster["sync_url"]
    try:
        command.downgrade(cfg, "base")
        command.upgrade(cfg, "head")
    finally:
        if prev is None:
            os.environ.pop("ALEMBIC_DATABASE_URL", None)
        else:
            os.environ["ALEMBIC_DATABASE_URL"] = prev

    # schema is back
    from sqlalchemy import create_engine

    sync_eng = create_engine(pg_cluster["sync_url"])
    with sync_eng.connect() as conn:
        rows = conn.execute(
            text("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
        )
        tables = {r[0] for r in rows}
    sync_eng.dispose()
    assert {"instruments", "market_bars", "ingestion_runs", "ingestion_state"} <= tables
