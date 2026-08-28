"""Step 7 - HistoricalVolatilityService runtime source migration + database-disabled mode."""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone

import pytest

from app.core.config import settings
from app.persistence.bar_source import PostgresHistoricalBarSource
from app.persistence.database import session_scope
from app.persistence.ingestion.trading_calendar import last_completed_session_date
from app.persistence.market_time import VN_TZ
from app.persistence.repositories.instrument_repository import InstrumentRepository, InstrumentUpsert
from app.persistence.repositories.market_bar_repository import MarketBarRepository
from app.persistence.rows import BarUpsert
from app.quant.historical_volatility_service import HistoricalVolatilityService

pytestmark = pytest.mark.asyncio
_CUTOFF = last_completed_session_date()


async def _seed_adjusted(symbol: str, n_sessions: int, *, base: float = 100.0) -> int:
    async with session_scope() as s:
        iid = (await InstrumentRepository(s).upsert(InstrumentUpsert(symbol=symbol, instrument_type="STOCK"))).id
        rows = []
        d = _CUTOFF
        i = 0
        while len(rows) < n_sessions and i < n_sessions * 3:
            if d.weekday() < 5:
                close = base * (1.0 + 0.012 * math.sin(len(rows) / 3.0))
                rows.append(BarUpsert(
                    instrument_id=iid, timeframe="1d",
                    ts=datetime(d.year, d.month, d.day, tzinfo=VN_TZ).astimezone(timezone.utc),
                    open=close, high=close * 1.01, low=close * 0.99, close=close, volume=1000,
                    price_basis="ADJUSTED", source="fiinquant", session_date=d,
                ))
            d -= timedelta(days=1)
            i += 1
        await MarketBarRepository(s).bulk_upsert_bars(list(reversed(rows)))
    return iid


async def test_hv_warmup_reads_postgres_with_zero_provider_calls(sessionmaker_, fake_provider):
    """Persist adjusted daily bars -> HV warm-up -> ZERO historical FiinQuant calls -> valid HV_22."""
    for sym in ("HPG", "VHM", "TCB"):
        await _seed_adjusted(sym, 60, base=100.0 + hash(sym) % 50)

    src = PostgresHistoricalBarSource(sessionmaker_)          # no gap_filler needed - data is present
    svc = HistoricalVolatilityService(bar_source=src)

    warmed = await svc.warm(["HPG", "VHM", "TCB"], timeout=10.0)
    assert fake_provider.calls == []                          # nothing hit the provider
    for sym in ("HPG", "VHM", "TCB"):
        est = warmed[sym]
        assert est is not None and est.value > 0
        assert est.source_label == f"HV_{svc.window}"
        assert svc.get_estimate(sym) is est                   # pure in-memory getter populated


async def test_hv_triggers_controlled_fill_when_postgres_history_insufficient(
    sessionmaker_, fake_provider, ingestion_service
):
    # only 5 persisted sessions -> below HV_POSTGRES_MIN_BARS_FOR_FILL -> controlled fill
    await _seed_adjusted("FPT", 5, base=90.0)
    fake_provider.seed_daily("FPT", _CUTOFF - timedelta(days=120), _CUTOFF, base=90.0, adjusted=True)

    src = PostgresHistoricalBarSource(
        sessionmaker_, gap_filler=ingestion_service, min_bars_for_fill=40,
    )
    svc = HistoricalVolatilityService(bar_source=src)
    est = await svc.refresh("FPT")

    assert len(fake_provider.calls) >= 1                      # controlled fill happened (off the tick path)
    assert est is not None and est.value > 0
    assert est.source_label == f"HV_{svc.window}"

    # a second refresh now finds enough persisted bars -> no further provider call
    fake_provider.calls.clear()
    est2 = await svc.refresh("FPT", force=True)
    assert fake_provider.calls == []
    assert est2 is not None


async def test_hv_fill_failure_is_non_fatal(sessionmaker_, fake_provider, ingestion_service):
    from app.market_data.market_schemas import HistoricalTransportError

    await _seed_adjusted("SSI", 45, base=70.0)   # enough bars already -> no fill needed
    fake_provider.fail_symbol["SSI"] = HistoricalTransportError("down")

    src = PostgresHistoricalBarSource(sessionmaker_, gap_filler=ingestion_service, min_bars_for_fill=40)
    svc = HistoricalVolatilityService(bar_source=src)
    est = await svc.refresh("SSI")
    assert est is not None and est.value > 0     # served from the 45 persisted bars
    assert fake_provider.calls == []             # threshold not crossed, no fill attempted


# --------------------------------------------------------------------------- #
# database-disabled / provider-direct mode
# --------------------------------------------------------------------------- #
async def test_provider_direct_mode_bypasses_postgres(engine, sessionmaker_, fake_provider, monkeypatch):
    from app.market_data.history_read_service import HistoryReadService

    monkeypatch.setattr(settings, "HISTORY_SOURCE_MODE", "provider_direct")
    fake_provider.seed_daily("HPG", _CUTOFF - timedelta(days=30), _CUTOFF)

    svc = HistoryReadService()
    svc.configure(engine=engine, sessionmaker=sessionmaker_, provider=fake_provider)
    assert svc.read_mode() == "provider_direct"

    bars = await svc.get_history("HPG", timeframe="1D", from_date=None, to_date=None, adjusted=True)
    assert len(bars) > 0
    assert len(fake_provider.calls) == 1                       # went straight to the provider
    assert svc.health()["counters"]["provider_direct_reads"] == 1


async def test_auto_mode_without_db_is_provider_direct(fake_provider, monkeypatch):
    from app.market_data.history_read_service import HistoryReadService

    monkeypatch.setattr(settings, "HISTORY_SOURCE_MODE", "auto")
    monkeypatch.setattr(settings, "DATABASE_ENABLED", False)
    fake_provider.seed_daily("HPG", date.today() - timedelta(days=10), date.today())

    svc = HistoryReadService()
    svc.set_provider(fake_provider)             # no configure() -> DB never wired
    assert svc.read_mode() == "provider_direct"
    await svc.get_history("HPG", timeframe="1D", from_date=None, to_date=None, adjusted=True)
    assert len(fake_provider.calls) == 1


async def test_non_daily_timeframe_is_always_provider_direct(history_service, fake_provider):
    """Only 1d is served PostgreSQL-first; 5m/30m stay provider-direct (no intraday persisted)."""
    fake_provider.seed_daily("HPG", _CUTOFF - timedelta(days=5), _CUTOFF)
    await history_service.get_history("HPG", timeframe="5m", from_date=None, to_date=None, adjusted=True)
    assert len(fake_provider.calls) == 1
    assert history_service.health()["counters"]["provider_direct_reads"] == 1


async def test_request_span_limit_rejected(history_service):
    from app.market_data.history_read_service import HistoryRequestError

    with pytest.raises(HistoryRequestError):
        await history_service.get_history(
            "HPG", timeframe="1D", from_date="2000-01-01", to_date="2026-08-01", adjusted=True
        )
    with pytest.raises(HistoryRequestError):
        await history_service.get_history(
            "HPG", timeframe="1D", from_date="2026-08-20", to_date="2026-08-01", adjusted=True
        )
