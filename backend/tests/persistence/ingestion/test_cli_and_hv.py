from __future__ import annotations

import math
from datetime import date, timedelta

import pytest
from sqlalchemy import func, select

from app.persistence.database import session_scope
from app.persistence.models import Instrument, MarketBar

pytestmark = pytest.mark.asyncio
_TODAY = date.today()


# ---- dry-run through the real handler, against the test DB ------------
async def test_cli_backfill_dry_run_zero_calls_zero_writes(engine, monkeypatch, capsys):
    """Drives app.persistence.cli._cmd_backfill with a fake provider + the test engine."""
    from app.persistence import cli
    from app.persistence import database as db
    from tests.persistence.ingestion.conftest import FakeHistoricalProvider

    fake = FakeHistoricalProvider()
    fake.seed_daily("HPG", _TODAY - timedelta(days=30), _TODAY)

    async def _make_service(_args):
        from app.persistence.ingestion.service import IngestionService

        sm = db.get_sessionmaker()
        return engine, IngestionService(engine=engine, sessionmaker=sm, bar_provider=fake, source="fiinquant")

    monkeypatch.setattr(cli, "_make_service", _make_service)

    class _NS:
        command = "backfill"
        json = True
        verbose = False
        database_url = None
        symbols = ["HPG"]
        timeframe = "1D"
        from_date = _TODAY - timedelta(days=800)
        to_date = _TODAY
        concurrency = None
        dry_run = True
        force = False
        include_forming = False
        adjusted = True

    rc = await cli._cmd_backfill(_NS())
    assert rc == 0
    assert fake.calls == []
    async with session_scope() as s:
        for model in (Instrument, MarketBar):
            assert (await s.execute(select(func.count()).select_from(model))).scalar_one() == 0


# ---- PostgresHistoricalBarSource feeds HV_22 from persisted bars ------
async def test_postgres_bar_source_feeds_hv_after_ingestion(ingestion_service, fake_provider, sessionmaker_):
    from app.persistence.bar_source import PostgresHistoricalBarSource
    from app.persistence.repositories.instrument_repository import InstrumentRepository, InstrumentUpsert
    from app.quant.historical_volatility_service import HistoricalVolatilityService

    async with session_scope() as s:
        await InstrumentRepository(s).upsert(InstrumentUpsert(symbol="HPG", instrument_type="STOCK"))

    # deterministic gently-oscillating adjusted closes for ~50 sessions
    start = _TODAY - timedelta(days=90)
    d = start
    px_i = 0
    while d <= _TODAY:
        if d.weekday() < 5:
            close = 100.0 * (1.0 + 0.015 * math.sin(px_i / 3.0))
            fake_provider.bars.setdefault("HPG", {})[d.isoformat()] = _bar(d, close)
            px_i += 1
        d += timedelta(days=1)

    res = await ingestion_service.backfill(
        ["HPG"], timeframe="1D", adjusted=True, from_date=start, to_date=_TODAY - timedelta(days=1)
    )
    assert res.status == "SUCCEEDED"

    # now read purely from PostgreSQL - no provider call happens here
    fake_provider.calls.clear()
    src = PostgresHistoricalBarSource(sessionmaker_)
    svc = HistoricalVolatilityService(bar_source=src)
    est = await svc.refresh("HPG")
    assert est is not None and est.value > 0
    assert est.source_label == f"HV_{svc.window}"
    assert svc.get_estimate("HPG") is est
    assert fake_provider.calls == []   # HV came entirely from persisted bars


def _bar(d: date, close: float):
    from app.market_data.market_schemas import HistoricalBar

    return HistoricalBar(date=d.isoformat(), open=close, high=close * 1.01, low=close * 0.99,
                         close=close, volume=1000, adjusted=True)
