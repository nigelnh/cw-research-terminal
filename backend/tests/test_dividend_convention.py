"""
Dividend-yield convention for Covered Warrant pricing.

Outcome of the q investigation: q = 0 is the **intentional, financially correct**
convention for HOSE covered warrants, because they are dividend-protected (issuer
adjusts strike/ratio on each ex-date). Using q > 0 would double-count that protection.

These tests lock:
  * the convention value + provenance (typed, immutable, decimal not percent)
  * that the LiveQuantEngine actually uses it (not a config env var)
  * that the SAME q flows into theoretical price, every IV inversion, and every Greek
  * that the choice is *material* - i.e. we pin q=0 deliberately, not because it is negligible
  * that dividends are not double-counted (effective adjusted strike is used AND q=0)
  * that the stateless what-if endpoint still accepts an arbitrary dividendYield

The q > 0 primitive tests in test_quant_black_scholes.py / test_quant_invariants.py
remain the proof that the BSM math itself supports q correctly - they are unaffected.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.quant.black_scholes import bs_call_price_share, calculate_analytical_greeks, solve_implied_volatility
from app.quant.dividend_convention import CW_DIVIDEND_YIELD_CONVENTION, DividendYieldConvention
from app.quant.quant_engine import LiveQuantEngine, calculate_time_to_maturity
from app.quant.quant_schemas import GreeksVolatilitySource
from app.instruments.instrument_schemas import (
    CoveredWarrantSpecification,
    InstrumentLifecycleStatus,
    DataQualityStatus,
    LifecycleEvidenceLevel,
    MetadataVerificationStatus,
)
from app.market_data.market_schemas import CanonicalQuote
from tests.fixtures.fake_bar_source import FakeBarSource, make_daily_bars, synthetic_closes
from app.quant.historical_volatility_service import HistoricalVolatilityService

client = TestClient(app)


@pytest.fixture(autouse=True)
def _freeze_engine_clock(monkeypatch):
    """Pin the engine's Vietnam wall-clock so time-to-maturity (and therefore every
    repriced figure below) is deterministic and does not drift across a date boundary.
    Test-only: no production code or quant formula is touched."""
    from datetime import datetime

    import app.quant.quant_engine as qe

    monkeypatch.setattr(qe, "get_vietnam_now", lambda: datetime(2026, 8, 29, 10, 0, 0, tzinfo=qe.VN_TZ))


# --------------------------------------------------------------------------- #
# The convention object
# --------------------------------------------------------------------------- #
def test_convention_value_is_zero():
    assert CW_DIVIDEND_YIELD_CONVENTION.value == 0.0
    assert isinstance(CW_DIVIDEND_YIELD_CONVENTION.value, float)


def test_convention_is_annualized_decimal_not_percent():
    # 0 <= q < 1 : an annualized decimal. A "3" meaning "3%" would be rejected.
    assert 0.0 <= CW_DIVIDEND_YIELD_CONVENTION.value < 1.0
    with pytest.raises(ValueError):
        DividendYieldConvention(value=3.0, rationale="pct slip", source="x")
    with pytest.raises(ValueError):
        DividendYieldConvention(value=-0.01, rationale="negative", source="x")


def test_convention_is_immutable_and_carries_provenance():
    from dataclasses import FrozenInstanceError

    with pytest.raises(FrozenInstanceError):
        CW_DIVIDEND_YIELD_CONVENTION.value = 0.03  # type: ignore[misc]
    assert "dividend-protected" in CW_DIVIDEND_YIELD_CONVENTION.rationale
    src = CW_DIVIDEND_YIELD_CONVENTION.source
    # provenance cites only public rules (VN regulatory framework + standard BSM)
    assert "regulatory framework" in src and "Black-Scholes" in src
    assert "legacy/" not in src and "F-05" not in src


def test_config_no_longer_exposes_a_dividend_yield_knob():
    # q must NOT be an env-overridable setting (that was the footgun).
    assert not hasattr(settings, "QUANT_DIVIDEND_YIELD")


# --------------------------------------------------------------------------- #
# The engine uses the convention, consistently
# --------------------------------------------------------------------------- #
def _spec():
    return CoveredWarrantSpecification(
        symbol="CHPG2602", issuer="TCBS", underlying_symbol="HPG",
        strike_price=25885.0, exercise_ratio=3.5704,
        maturity_date="2026-12-19", last_trading_date="2026-12-17",
        status=InstrumentLifecycleStatus.ACTIVE, data_quality=DataQualityStatus.COMPLETE,
        evidence_level=LifecycleEvidenceLevel.CURRENT_EXCHANGE_LIST,
        metadata_verification=MetadataVerificationStatus.VERIFIED_CURRENT,
    )


async def _engine_with_hv():
    svc = HistoricalVolatilityService(bar_source=FakeBarSource({"HPG": make_daily_bars(synthetic_closes(40))}))
    await svc.warm(["HPG"])
    eng = LiveQuantEngine()
    eng.set_historical_vol_getter(svc.get_estimate)
    return eng


@pytest.mark.asyncio
async def test_engine_reports_convention_q_in_model_inputs():
    eng = await _engine_with_hv()
    und = CanonicalQuote(symbol="HPG", instrument_type="STOCK", last_price=26500.0)
    cw = CanonicalQuote(symbol="CHPG2602", instrument_type="CW", bid1_price=1200.0, ask1_price=1250.0, last_price=1220.0)
    a = await eng.compute_warrant_analytics("CHPG2602", spec=_spec(), cw_state=cw, und_state=und)

    assert a.model_inputs is not None
    assert a.model_inputs.dividend_yield == CW_DIVIDEND_YIELD_CONVENTION.value == 0.0


@pytest.mark.asyncio
async def test_engine_uses_same_q_for_price_iv_and_greeks():
    """The SAME q (0.0) must drive the theoretical price, every IV solve, and the Greeks.
    Verified by reproducing each output from the model inputs with q = 0 explicitly."""
    eng = await _engine_with_hv()
    und = CanonicalQuote(symbol="HPG", instrument_type="STOCK", last_price=26500.0)
    cw = CanonicalQuote(symbol="CHPG2602", instrument_type="CW", bid1_price=1200.0, ask1_price=1260.0, last_price=1230.0)
    a = await eng.compute_warrant_analytics("CHPG2602", spec=_spec(), cw_state=cw, und_state=und)
    mi = a.model_inputs
    assert mi is not None and mi.underlying_price is not None and mi.strike_price is not None
    assert mi.time_to_maturity is not None and mi.exercise_ratio is not None
    S, K, k = mi.underlying_price, mi.strike_price, mi.exercise_ratio
    r = mi.risk_free_rate
    q0 = 0.0
    # canonical full-precision T (clock is frozen by the autouse fixture); the 5dp value
    # in model_inputs is a display echo, verified separately.
    T, _dte = calculate_time_to_maturity(_spec().maturity_date)
    assert mi.time_to_maturity == round(T, 5)

    # theoretical price reprices exactly at q = 0 with the HV it reports
    assert a.theoretical_volatility is not None
    assert a.theoretical_price == round(bs_call_price_share(S, K, T, r, q0, a.theoretical_volatility) / k, 2)
    # model_price_at_iv_mid reprices at q = 0 with iv_mid
    assert a.iv_mid is not None and a.model_price_at_iv_mid is not None
    assert a.model_price_at_iv_mid == pytest.approx(
        round(bs_call_price_share(S, K, T, r, q0, a.iv_mid) / k, 2), abs=0.5
    )
    # every solved IV inverts at q = 0 (bid/ask/trade)
    for iv, px in ((a.iv_bid, 1200.0), (a.iv_ask, 1260.0), (a.iv_trade, 1230.0)):
        assert iv is not None
        assert bs_call_price_share(S, K, T, r, q0, iv) / k == pytest.approx(px, abs=1.0)
    # Greeks match a direct q = 0 call at the volatility the engine ACTUALLY used (full
    # a.iv_trade), reproduced exactly. `greeks.volatility_used` is the 4dp display echo.
    assert a.greeks.volatility_source == GreeksVolatilitySource.IV_TRADE
    assert a.iv_trade is not None
    assert a.greeks.volatility_used == round(a.iv_trade, 4)
    direct = calculate_analytical_greeks(S, K, T, r, q0, a.iv_trade, exercise_ratio=k)
    assert a.greeks.delta == direct.delta
    assert a.greeks.theta == direct.theta
    assert a.greeks.vega == direct.vega


@pytest.mark.asyncio
async def test_engine_uses_effective_adjusted_strike_and_q_zero_no_double_count():
    """Dividends enter CW valuation exactly ONCE - through the corporate-action-adjusted
    effective strike/ratio. q stays 0, so the dividend effect is not applied twice."""
    eng = await _engine_with_hv()
    spec = CoveredWarrantSpecification(
        symbol="CHPG2602", issuer="TCBS", underlying_symbol="HPG",
        initial_strike_price=29000.0, initial_exercise_ratio=4.0,        # pre-adjustment
        effective_strike_price=25885.0, effective_exercise_ratio=3.5704,  # post-HPG-dividend adjustment
        strike_price=25885.0, exercise_ratio=3.5704, is_adjusted=True, terms_effective_date="2026-08-01",
        maturity_date="2026-12-19", last_trading_date="2026-12-17",
        status=InstrumentLifecycleStatus.ACTIVE, data_quality=DataQualityStatus.COMPLETE,
        evidence_level=LifecycleEvidenceLevel.CURRENT_EXCHANGE_LIST,
        metadata_verification=MetadataVerificationStatus.VERIFIED_CURRENT,
    )
    und = CanonicalQuote(symbol="HPG", instrument_type="STOCK", last_price=26500.0)
    cw = CanonicalQuote(symbol="CHPG2602", instrument_type="CW", bid1_price=1200.0, ask1_price=1250.0)
    a = await eng.compute_warrant_analytics("CHPG2602", spec=spec, cw_state=cw, und_state=und)

    assert a.model_inputs is not None
    assert a.model_inputs.strike_price == 25885.0                     # adjusted, not 29000
    assert a.model_inputs.exercise_ratio == 3.5704                    # adjusted, not 4.0
    assert a.model_inputs.dividend_yield == 0.0                       # NOT also applied as q


# --------------------------------------------------------------------------- #
# The choice is material - we pin q=0 on purpose, not because it is negligible
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "label,S,K,T,sigma,k,min_price_drop_pct",
    [
        ("OTM HPG-like",  22150.0, 25885.0, 0.30, 0.22, 3.5704, 8.0),
        ("ATM",           28000.0, 28000.0, 0.40, 0.35, 2.0,    3.5),
        ("ITM VHM-like",  30000.0, 25000.0, 0.50, 0.30, 4.0,    3.0),
    ],
)
def test_naive_positive_q_would_materially_underprice(label, S, K, T, sigma, k, min_price_drop_pct):
    """If someone plugged in a trailing dividend yield (q = 3%), the theoretical CW price
    would fall by a MATERIAL amount vs the correct q = 0. This is exactly why q = 0 is
    pinned by convention rather than sourced from dividend data."""
    r = 0.05
    p0 = calculate_analytical_greeks(S, K, T, r, 0.0, sigma, exercise_ratio=k).theoretical_price
    p3 = calculate_analytical_greeks(S, K, T, r, 0.03, sigma, exercise_ratio=k).theoretical_price
    assert p0 is not None and p3 is not None
    drop_pct = (p0 - p3) / p0 * 100.0
    assert drop_pct > min_price_drop_pct, f"{label}: q=3% only moved price {drop_pct:.1f}%"

    # direction sanity: q>0 lowers a call, lowers delta, raises (less negative) theta
    d0 = calculate_analytical_greeks(S, K, T, r, 0.0, sigma, exercise_ratio=k)
    d3 = calculate_analytical_greeks(S, K, T, r, 0.03, sigma, exercise_ratio=k)
    assert d0.delta is not None and d3.delta is not None and d3.delta < d0.delta
    assert d0.theta is not None and d3.theta is not None
    assert d3.theta > d0.theta          # +q S e^{-qT} N(d1) term makes theta less negative


def test_iv_shifts_materially_if_q_assumption_changes_at_fixed_market_price():
    """Holding the observed CW price fixed, changing the q assumption from 0 to 3% shifts
    the implied vol by > 50 bps for a representative case - a self-consistency hazard the
    q=0 convention avoids."""
    S, K, T, k, r = 28000.0, 28000.0, 0.40, 2.0, 0.05
    mkt_cw = round(bs_call_price_share(S, K, T, r, 0.0, 0.35) / k, 2)
    iv0, _ = solve_implied_volatility(S, K, T, r, 0.0, mkt_cw, exercise_ratio=k)
    iv3, _ = solve_implied_volatility(S, K, T, r, 0.03, mkt_cw, exercise_ratio=k)
    assert iv0 is not None and iv3 is not None
    assert (iv3 - iv0) * 1e4 > 50.0     # > 50 bps


# --------------------------------------------------------------------------- #
# Stateless what-if endpoint still honours an explicit dividendYield
# --------------------------------------------------------------------------- #
def test_stateless_calculate_endpoint_still_accepts_whatif_q():
    body = {
        "underlyingPrice": 28000.0, "strikePrice": 28000.0, "timeToMaturity": 0.40,
        "riskFreeRate": 0.05, "volatility": 0.35, "exerciseRatio": 2.0,
    }
    r0 = client.post("/api/quant/calculate", json={**body, "dividendYield": 0.0})
    r3 = client.post("/api/quant/calculate", json={**body, "dividendYield": 0.03})
    assert r0.status_code == 200 and r3.status_code == 200
    p0 = r0.json()["theoreticalPrice"]
    p3 = r3.json()["theoreticalPrice"]
    assert p0 is not None and p3 is not None
    assert p3 < p0                                   # what-if q=3% lowers the price
    assert (p0 - p3) / p0 > 0.03                     # by a material amount


def test_stateless_calculate_defaults_q_to_zero():
    body = {
        "underlyingPrice": 28000.0, "strikePrice": 28000.0, "timeToMaturity": 0.40,
        "riskFreeRate": 0.05, "volatility": 0.35, "exerciseRatio": 2.0,
    }
    r_default = client.post("/api/quant/calculate", json=body)
    r_explicit0 = client.post("/api/quant/calculate", json={**body, "dividendYield": 0.0})
    assert r_default.status_code == 200
    assert r_default.json()["theoreticalPrice"] == pytest.approx(
        r_explicit0.json()["theoreticalPrice"], abs=1e-6
    )
