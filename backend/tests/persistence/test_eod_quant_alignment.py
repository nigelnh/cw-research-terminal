"""EOD / last-session quant analytics - temporal alignment (Step 13C Workstream D).

Both legs are read for the SAME session_date. A missing leg -> EOD_INPUT_MISSING, never a
mixed-day calculation. CONFLICTING metadata still gates the engine closed.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app.instruments.instrument_registry import instrument_registry
from app.persistence.repositories.instrument_repository import InstrumentRepository, InstrumentUpsert
from app.persistence.repositories.market_bar_repository import MarketBarRepository
from app.persistence.rows import BarUpsert
from app.quant.quant_engine import live_quant_engine

pytestmark = pytest.mark.asyncio

_VN = timezone(timedelta(hours=7))
_D = date(2026, 8, 28)      # a Friday, well inside CVPB2615's life
_DM1 = date(2026, 8, 27)


async def _bar(sm, sym, itype, pb, d, close):
    async with sm() as s:
        iid = (await InstrumentRepository(s).upsert(
            InstrumentUpsert(symbol=sym, instrument_type=itype)
        )).id
        await s.commit()
    async with sm() as s:
        await MarketBarRepository(s).bulk_upsert_bars([
            BarUpsert(
                instrument_id=iid, timeframe="1d",
                ts=datetime(d.year, d.month, d.day, tzinfo=_VN).astimezone(timezone.utc),
                open=close, high=close, low=close, close=close, volume=1000,
                price_basis=pb, source="fiinquant",
            )
        ])
        await s.commit()


@pytest.fixture(autouse=True)
def _wire(sessionmaker_, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "DATABASE_ENABLED", True)
    live_quant_engine._eod_cache.clear()  # noqa: SLF001
    live_quant_engine._eod_close_cache.clear()  # noqa: SLF001
    # HV getter: a fixed estimate so Greeks/theo are computable deterministically.
    class _HV:
        value = 0.35
        source_label = "HV_22"
    monkeypatch.setattr(live_quant_engine, "_historical_vol_getter", lambda s: _HV())
    yield


async def test_aligned_session_produces_analytics(sessionmaker_):
    await instrument_registry.initialize(current_date="2026-08-28")
    await _bar(sessionmaker_, "CVPB2615", "CW", "RAW", _D, 900.0)
    await _bar(sessionmaker_, "VPB", "STOCK", "ADJUSTED", _D, 22000.0)

    a = await live_quant_engine.compute_eod_analytics("CVPB2615", _D, sessionmaker=sessionmaker_)
    assert a.is_available is True
    assert a.calculated_at.startswith("2026-08-28T15:00")
    assert a.model_inputs is not None and a.model_inputs.underlying_price == 22000.0
    assert a.iv_trade is not None            # CW last + underlying close both known
    assert a.greeks is not None and a.greeks.delta is not None
    assert a.iv_bid is None and a.iv_ask is None  # no EOD order book


async def test_missing_underlying_leg_is_eod_input_missing(sessionmaker_):
    await instrument_registry.initialize(current_date="2026-08-28")
    await _bar(sessionmaker_, "CVPB2615", "CW", "RAW", _D, 900.0)
    # underlying bar for _D deliberately NOT seeded (only the previous day)
    await _bar(sessionmaker_, "VPB", "STOCK", "ADJUSTED", _DM1, 21000.0)

    a = await live_quant_engine.compute_eod_analytics("CVPB2615", _D, sessionmaker=sessionmaker_)
    assert a.is_available is False
    assert "EOD_INPUT_MISSING" in a.unavailable_reason
    assert "VPB@2026-08-28" in a.unavailable_reason


async def test_does_not_mix_cw_dm1_with_underlying_d(sessionmaker_):
    await instrument_registry.initialize(current_date="2026-08-28")
    await _bar(sessionmaker_, "CVPB2615", "CW", "RAW", _DM1, 850.0)   # CW only on D-1
    await _bar(sessionmaker_, "VPB", "STOCK", "ADJUSTED", _D, 22000.0)  # underlying only on D

    a = await live_quant_engine.compute_eod_analytics("CVPB2615", _D, sessionmaker=sessionmaker_)
    # session_date=D: CW leg for D is absent -> no analytics, never uses the D-1 CW close.
    assert a.is_available is False
    assert "cw@2026-08-28" in a.unavailable_reason


async def test_conflicting_metadata_still_gated(sessionmaker_):
    await instrument_registry.initialize(current_date="2026-08-28")
    await _bar(sessionmaker_, "CTCB2601", "CW", "RAW", _D, 500.0)
    await _bar(sessionmaker_, "TCB", "STOCK", "ADJUSTED", _D, 34000.0)

    a = await live_quant_engine.compute_eod_analytics("CTCB2601", _D, sessionmaker=sessionmaker_)
    assert a.is_available is False
    assert "METADATA_NOT_VERIFIED_CURRENT" in a.unavailable_reason
    assert "CONFLICTING" in a.unavailable_reason
