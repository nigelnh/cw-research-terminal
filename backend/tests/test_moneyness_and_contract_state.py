"""Moneyness ATM band + contract lifecycle state (Step 13A).

- moneyness numeric value is raw S/K; the ITM/ATM/OTM label uses QUANT_MONEYNESS_ATM_BAND.
- contract_state / is_tradable are derived from last_trading_date & maturity_date and are
  truthful even when analytics are unavailable.
- a non-tradable warrant never returns live IV/greeks.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from app.core.config import settings
from app.quant.quant_engine import derive_contract_state, get_vietnam_now, VN_TZ, LiveQuantEngine
from app.quant.quant_schemas import ContractLifecycleState, MoneynessCategory
from app.instruments.instrument_schemas import (
    CoveredWarrantSpecification, InstrumentLifecycleStatus, DataQualityStatus,
    LifecycleEvidenceLevel, MetadataVerificationStatus,
)
from app.market_data.market_schemas import CanonicalQuote

pytestmark = pytest.mark.asyncio


def _now(y, m, d):
    return datetime(y, m, d, 10, 0, tzinfo=VN_TZ)


# ---------------------------------------------------------------- contract state
@pytest.mark.parametrize("today,expected,tradable", [
    (_now(2026, 1, 1), ContractLifecycleState.ACTIVE, True),
    (_now(2026, 10, 12), ContractLifecycleState.NEAR_EXPIRY, True),   # within 10d of last trading 2026-10-22
    (_now(2026, 10, 22), ContractLifecycleState.LAST_TRADING_DAY, True),
    (_now(2026, 10, 24), ContractLifecycleState.PENDING_MATURITY, False),  # past last trading, <= maturity 2026-10-26
    (_now(2026, 10, 27), ContractLifecycleState.EXPIRED, False),
])
async def test_contract_state_transitions(today, expected, tradable):
    state, is_tradable = derive_contract_state("2026-10-22", "2026-10-26", now=today)
    assert state == expected
    assert is_tradable is tradable


async def test_contract_state_unknown_when_no_dates():
    state, is_tradable = derive_contract_state(None, None)
    assert state == ContractLifecycleState.UNKNOWN and is_tradable is False


# ---------------------------------------------------------------- ATM band
def _spec(strike: float) -> CoveredWarrantSpecification:
    return CoveredWarrantSpecification(
        symbol="CTEST2699", issuer="ACBS", underlying_symbol="VPB",
        strike_price=strike, exercise_ratio=2.0,
        effective_strike_price=strike, effective_exercise_ratio=2.0,
        maturity_date="2099-02-17", last_trading_date="2099-02-15",
        status=InstrumentLifecycleStatus.ACTIVE, data_quality=DataQualityStatus.COMPLETE,
        evidence_level=LifecycleEvidenceLevel.MANUAL_SNAPSHOT,
        metadata_verification=MetadataVerificationStatus.VERIFIED_CURRENT,
    )


@pytest.mark.parametrize("S,K,expected_cat", [
    (10301.0, 10000.0, MoneynessCategory.ITM),   # +3.01% -> ITM (> 1.03)
    (10300.0, 10000.0, MoneynessCategory.ATM),   # exactly +3.00% -> band is inclusive -> ATM
    (10250.0, 10000.0, MoneynessCategory.ATM),   # +2.5% -> ATM
    (10000.0, 10000.0, MoneynessCategory.ATM),   # parity -> ATM
    (9750.0, 10000.0, MoneynessCategory.ATM),    # -2.5% -> ATM
    (9700.0, 10000.0, MoneynessCategory.ATM),    # exactly -3.00% -> ATM
    (9699.0, 10000.0, MoneynessCategory.OTM),    # -3.01% -> OTM (< 0.97)
])
async def test_moneyness_band_boundaries(S, K, expected_cat):
    eng = LiveQuantEngine()
    und = CanonicalQuote(symbol="VPB", last_price=S)
    cw = CanonicalQuote(symbol="CTEST2699", bid1_price=100.0, ask1_price=110.0, last_price=None)
    a = await eng.compute_warrant_analytics("CTEST2699", spec=_spec(K), cw_state=cw, und_state=und)
    assert a.is_available is True
    assert a.moneyness == round(S / K, 5)          # raw numeric, unaffected by band
    assert a.moneyness_category == expected_cat


async def test_atm_band_is_config_driven(monkeypatch):
    monkeypatch.setattr(settings, "QUANT_MONEYNESS_ATM_BAND", 0.005)  # tight 0.5% band
    eng = LiveQuantEngine()
    und = CanonicalQuote(symbol="VPB", last_price=10200.0)            # +2% -> now ITM
    cw = CanonicalQuote(symbol="CTEST2699", bid1_price=100.0, ask1_price=110.0)
    a = await eng.compute_warrant_analytics("CTEST2699", spec=_spec(10000.0), cw_state=cw, und_state=und)
    assert a.moneyness_category == MoneynessCategory.ITM


# ---------------------------------------------------------------- non-tradable clears analytics
async def test_non_tradable_warrant_returns_no_live_analytics(monkeypatch):
    monkeypatch.setattr(_qe_now(), "get_vietnam_now", lambda: _now(2026, 10, 24))
    eng = LiveQuantEngine()
    spec = _spec(10000.0)
    spec = spec.model_copy(update={"maturity_date": "2026-10-26", "last_trading_date": "2026-10-22"})
    und = CanonicalQuote(symbol="VPB", last_price=10500.0)
    cw = CanonicalQuote(symbol="CTEST2699", bid1_price=500.0, ask1_price=520.0)
    a = await eng.compute_warrant_analytics("CTEST2699", spec=spec, cw_state=cw, und_state=und)
    assert a.contract_state == ContractLifecycleState.PENDING_MATURITY
    assert a.is_tradable is False
    assert a.is_available is False
    assert a.unavailable_reason and "NOT_TRADABLE" in a.unavailable_reason
    assert a.iv_bid is None and a.iv_ask is None
    assert a.greeks.delta is None


def _qe_now():
    import app.quant.quant_engine as m
    return m
