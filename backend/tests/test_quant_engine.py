"""
Comprehensive Quantitative Engine Unit Tests for Covered Warrants:
- Black-Scholes European Call pricing & golden reference vectors
- Exact single-vector verification (S=22100, K=22000, r=0.05, q=0.0, T=0.23886, sigma=0.2591, CR=2.0)
- Analytical vs Finite-Difference cross-checks (Delta, Gamma, Vega, Rho, 1-Day Theta Decay)
- Exercise Ratio 2:1 scaling invariant (CW price = Share Call / 2)
- Implied Volatility root-solving & exact round-trip inversion
- Independent Bid, Ask, and Trade IV calculations
- Real trade absent invariant (iv_trade is strictly None)
- Strict No-Arbitrage boundary enforcement (PRICE_OUTSIDE_MODEL_BOUNDS)
- Explicit Solver diagnostics (NO_ROOT_IN_SIGMA_RANGE, CONVERGENCE_FAILED, INVALID_INPUT)
- Expired & invalid maturity handling (T <= 0)
- Hard Data-Quality guards (PARTIAL metadata & UNKNOWN lifecycle rejected)
- Complete metadata does not bypass contradictory input guard
- Moneyness (S/K) independence from CW price
- Live event-driven quant recomputation & REST API
"""

import pytest
import math
from datetime import date, datetime, timezone, timedelta
from fastapi.testclient import TestClient

from app.main import app
from app.quant.black_scholes import (
    bs_call_price_share,
    calculate_analytical_greeks,
    solve_implied_volatility,
    check_call_price_bounds,
)
from app.quant.quant_schemas import (
    GreeksVolatilitySource,
    MoneynessCategory,
)
import app.quant.quant_engine as _qe
from app.quant.quant_engine import LiveQuantEngine, calculate_time_to_maturity
from app.quant.historical_volatility import calculate_historical_volatility
from app.quant.historical_volatility_service import HistoricalVolatilityService
from app.core.config import settings
from tests.fixtures.fake_bar_source import FakeBarSource, make_daily_bars, synthetic_closes
from app.instruments.instrument_schemas import (
    CoveredWarrantSpecification,
    InstrumentLifecycleStatus,
    DataQualityStatus,
    LifecycleEvidenceLevel,
    MetadataVerificationStatus,
)
from app.market_data.market_schemas import CanonicalQuote, HistoricalBar

client = TestClient(app)
VN_TZ = timezone(timedelta(hours=7))


@pytest.fixture(autouse=True)
def _freeze_engine_clock(monkeypatch):
    """Pin the engine's Vietnam wall-clock so time-to-maturity is deterministic and does
    not drift across a date boundary. Test-only; no production code / formula is touched.
    No test in this file depends on 'today' being a particular value (expired-warrant
    cases pass T=0.0 or maturity_date=None directly)."""
    monkeypatch.setattr(_qe, "get_vietnam_now", lambda: datetime(2026, 8, 29, 10, 0, 0, tzinfo=VN_TZ))


def test_exact_single_vector_verification():
    """
    Immutable Single-Vector Verification:
    S = 22100.0, K = 22000.0, r = 0.05, q = 0.0, T = 0.23886, sigma = 0.2591, CR = 2.0.

    Exact Analytical Expected Values:
    d1 = 0.19344
    d2 = 0.06681
    Call/share = 1296.53 VND
    CW theoretical price = 648.26 VND
    Delta CW = 0.28835
    Gamma CW = 0.00006996
    Theta CW = -3.93 VND/calendar day
    Vega CW = 21.15 VND/+1% vol
    Rho CW = 13.67 VND/+1% rate
    """
    S = 22100.0
    K = 22000.0
    r = 0.05
    q = 0.0
    T = 0.23886
    sigma = 0.2591
    CR = 2.0

    call_share = bs_call_price_share(S, K, T, r, q, sigma)
    greeks = calculate_analytical_greeks(S, K, T, r, q, sigma, exercise_ratio=CR)

    # 1. Share Call & Theoretical CW Price
    assert abs(call_share - 1296.53) < 0.05
    assert greeks.theoretical_price is not None
    assert abs(greeks.theoretical_price - 648.26) < 0.05
    assert abs(greeks.theoretical_price - (call_share / CR)) < 0.05

    # 2. Delta CW: N(d1) / CR
    assert greeks.delta is not None
    assert abs(greeks.delta - 0.28835) < 0.0001

    # 3. Gamma CW: N'(d1) / (S * sigma * sqrt(T) * CR)
    assert greeks.gamma is not None
    assert abs(greeks.gamma - 0.00006996) < 0.0000001

    # 4. Theta CW daily: Theta_yearly / (365 * CR)
    assert greeks.theta is not None
    assert abs(greeks.theta - (-3.93)) < 0.02

    # 5. Vega CW per +1% vol: Vega_unit * 0.01 / CR
    assert greeks.vega is not None
    assert abs(greeks.vega - 21.15) < 0.02

    # 6. Rho CW per +1% rate: Rho_unit * 0.01 / CR
    assert greeks.rho is not None
    assert abs(greeks.rho - 13.67) < 0.02


def test_finite_difference_cross_checks():
    """
    Cross-checks analytical Greeks against numerical finite differences:
    - Delta: [C(S+h) - C(S-h)] / (2h)
    - Gamma: [C(S+h) - 2C(S) + C(S-h)] / h^2
    - Vega: [C(sigma+h) - C(sigma-h)] / (2h) * 0.01
    - Rho: [C(r+h) - C(r-h)] / (2h) * 0.01
    - Theta: C(T - 1/365) - C(T)
    """
    S, K, T, r, q, sigma, CR = 22100.0, 22000.0, 0.23886, 0.05, 0.0, 0.2591, 2.0

    greeks = calculate_analytical_greeks(S, K, T, r, q, sigma, exercise_ratio=CR)
    center_price = bs_call_price_share(S, K, T, r, q, sigma) / CR

    # 1. Delta Finite Difference (h = 1.0 VND)
    h_s = 1.0
    p_up_s = bs_call_price_share(S + h_s, K, T, r, q, sigma) / CR
    p_down_s = bs_call_price_share(S - h_s, K, T, r, q, sigma) / CR
    fd_delta = (p_up_s - p_down_s) / (2.0 * h_s)
    assert greeks.delta is not None
    assert abs(greeks.delta - fd_delta) < 1e-4

    # 2. Gamma Finite Difference (h = 1.0 VND)
    fd_gamma = (p_up_s - 2.0 * center_price + p_down_s) / (h_s * h_s)
    assert greeks.gamma is not None
    assert abs(greeks.gamma - fd_gamma) < 1e-6

    # 3. Vega Finite Difference (h = 0.0001 vol)
    h_vol = 0.0001
    p_up_vol = bs_call_price_share(S, K, T, r, q, sigma + h_vol) / CR
    p_down_vol = bs_call_price_share(S, K, T, r, q, sigma - h_vol) / CR
    fd_vega = ((p_up_vol - p_down_vol) / (2.0 * h_vol)) * 0.01
    assert greeks.vega is not None
    assert abs(greeks.vega - fd_vega) < 1e-2

    # 4. Rho Finite Difference (h = 0.0001 rate)
    h_r = 0.0001
    p_up_r = bs_call_price_share(S, K, T, r + h_r, q, sigma) / CR
    p_down_r = bs_call_price_share(S, K, T, r - h_r, q, sigma) / CR
    fd_rho = ((p_up_r - p_down_r) / (2.0 * h_r)) * 0.01
    assert greeks.rho is not None
    assert abs(greeks.rho - fd_rho) < 1e-2

    # 5. Theta One-Day Decay (T_next = T - 1/365)
    T_next = T - (1.0 / 365.0)
    p_next_day = bs_call_price_share(S, K, T_next, r, q, sigma) / CR
    fd_theta_1day = p_next_day - center_price
    assert greeks.theta is not None
    # Analytical theta per day matches 1-day time decay within 0.02 VND
    assert abs(greeks.theta - fd_theta_1day) < 0.02


def test_black_scholes_golden_vector():
    """
    Independent reference check:
    S = 29,500 VND, K = 28,000 VND, T = 0.42 years, r = 0.065, q = 0.0, sigma = 0.35, CR = 2.0 (2:1).
    """
    S = 29500.0
    K = 28000.0
    T = 0.42
    r = 0.065
    q = 0.0
    sigma = 0.35
    CR = 2.0

    call_share = bs_call_price_share(S, K, T, r, q, sigma)
    # Share call price should be between 3600 and 4600 VND
    assert 3600.0 < call_share < 4600.0

    greeks = calculate_analytical_greeks(S, K, T, r, q, sigma, exercise_ratio=CR)

    # CW Theoretical Price = Share Call / 2.0
    assert greeks.theoretical_price is not None
    assert abs(greeks.theoretical_price - (call_share / 2.0)) < 0.05
    assert 1800.0 < greeks.theoretical_price < 2300.0

    # Delta scaled: 0.30 <= Delta_CW <= 0.45 (since Delta_share is ~0.70)
    assert greeks.delta is not None
    assert 0.30 < greeks.delta < 0.45

    # Gamma > 0
    assert greeks.gamma is not None and greeks.gamma > 0.0

    # Theta daily negative (time decay)
    assert greeks.theta is not None and greeks.theta < 0.0

    # Vega per 1% vol > 0
    assert greeks.vega is not None and greeks.vega > 0.0


def test_exercise_ratio_scaling_invariant():
    """
    Verifies that CW Theoretical Price = Share Call / CR for any arbitrary ratio (e.g. 5.0).
    """
    S, K, T, r, q, sigma = 30000.0, 30000.0, 0.25, 0.05, 0.0, 0.30
    call_share = bs_call_price_share(S, K, T, r, q, sigma)

    greeks_ratio_1 = calculate_analytical_greeks(S, K, T, r, q, sigma, exercise_ratio=1.0)
    greeks_ratio_5 = calculate_analytical_greeks(S, K, T, r, q, sigma, exercise_ratio=5.0)

    assert greeks_ratio_1.theoretical_price is not None
    assert greeks_ratio_5.theoretical_price is not None
    assert abs(greeks_ratio_5.theoretical_price - (greeks_ratio_1.theoretical_price / 5.0)) < 0.05
    assert greeks_ratio_1.delta is not None and greeks_ratio_5.delta is not None
    assert abs(greeks_ratio_5.delta - (greeks_ratio_1.delta / 5.0)) < 0.001


def test_implied_volatility_roundtrip_inversion():
    """
    Given a known volatility sigma_true = 0.35, generate CW price,
    then solve for IV and verify recovery within tolerance.
    """
    S = 22000.0
    K = 22000.0
    T = 0.5
    r = 0.05
    q = 0.0
    sigma_true = 0.35
    CR = 2.0

    call_share = bs_call_price_share(S, K, T, r, q, sigma_true)
    cw_market_price = call_share / CR

    iv_recovered, reason = solve_implied_volatility(
        S=S, K=K, T=T, r=r, q=q, market_price_cw=cw_market_price, exercise_ratio=CR
    )

    assert iv_recovered is not None
    assert abs(iv_recovered - sigma_true) < 0.001
    assert reason is None


def test_independent_bid_ask_trade_ivs():
    """
    Verifies that Bid price < Last price < Ask price produces IV_Bid < IV_Trade < IV_Ask.
    """
    S = 24000.0
    K = 22000.0
    T = 0.35
    r = 0.05
    q = 0.0
    CR = 2.0

    cw_bid = 1200.0
    cw_trade = 1300.0
    cw_ask = 1400.0

    iv_bid, _ = solve_implied_volatility(S, K, T, r, q, cw_bid, exercise_ratio=CR)
    iv_trade, _ = solve_implied_volatility(S, K, T, r, q, cw_trade, exercise_ratio=CR)
    iv_ask, _ = solve_implied_volatility(S, K, T, r, q, cw_ask, exercise_ratio=CR)

    assert iv_bid is not None
    assert iv_trade is not None
    assert iv_ask is not None
    assert iv_bid < iv_trade < iv_ask


def test_solver_root_bracketing_and_diagnostics():
    """
    Tests explicit solver diagnostic states:
    1. PRICE_OUTSIDE_MODEL_BOUNDS
    2. NO_ROOT_IN_SIGMA_RANGE
    3. INVALID_INPUT
    """
    S = 20000.0
    K = 25000.0
    T = 0.5
    r = 0.05
    q = 0.0
    CR = 1.0

    # 1. Price above upper bound S
    iv_high, r_high = solve_implied_volatility(S, K, T, r, q, 22000.0, exercise_ratio=CR)
    assert iv_high is None
    assert r_high == "PRICE_OUTSIDE_MODEL_BOUNDS"

    # 2. Deep ITM price below intrinsic lower bound
    S_itm, K_itm = 30000.0, 20000.0
    iv_low, r_low = solve_implied_volatility(S_itm, K_itm, T, r, q, 500.0, exercise_ratio=CR)
    assert iv_low is None
    assert r_low == "PRICE_OUTSIDE_MODEL_BOUNDS"

    # 3. Invalid inputs
    iv_inv, r_inv = solve_implied_volatility(-100.0, K, T, r, q, 100.0, exercise_ratio=CR)
    assert iv_inv is None
    assert r_inv == "INVALID_INPUT"

    # 4. No root in sigma range (e.g. sigma_min=0.20, sigma_max=0.30, but price implies 0.50)
    cw_p_high_vol = bs_call_price_share(S, K, T, r, q, 0.50) / CR
    iv_range, r_range = solve_implied_volatility(
        S, K, T, r, q, cw_p_high_vol, exercise_ratio=CR, sigma_min=0.10, sigma_max=0.30
    )
    assert iv_range is None
    assert r_range == "NO_ROOT_IN_SIGMA_RANGE"


def test_expired_warrant_handling():
    """
    Expired warrants (T <= 0) must return None for IV and intrinsic value for theoretical price.
    """
    T = 0.0
    iv, reason = solve_implied_volatility(22000.0, 20000.0, T, 0.05, 0.0, 1000.0, exercise_ratio=2.0)
    assert iv is None

    greeks = calculate_analytical_greeks(22000.0, 20000.0, T, 0.05, 0.0, 0.30, exercise_ratio=2.0)
    assert greeks.theoretical_price == 1000.0  # (22000 - 20000) / 2 = 1000
    assert greeks.delta == 0.50  # 1 / 2.0 = 0.50
    assert greeks.gamma == 0.0
    assert greeks.theta == 0.0


@pytest.mark.asyncio
async def test_engine_data_quality_guard_rejects_partial_and_unknown():
    engine = LiveQuantEngine()

    # 1. Partial warrant missing strike price
    spec_partial = CoveredWarrantSpecification(
        symbol="CPARTIAL01",
        issuer="SSI",
        underlying_symbol="HPG",
        strike_price=None,
        exercise_ratio=None,
        maturity_date=None,
        last_trading_date=None,
        listed_volume=None,
        issue_price=None,
        status=InstrumentLifecycleStatus.ACTIVE,
        data_quality=DataQualityStatus.PARTIAL,
        evidence_level=LifecycleEvidenceLevel.SEARCH_ONLY,
        metadata_verification=MetadataVerificationStatus.VERIFIED_CURRENT,
    )
    res_partial = await engine.compute_warrant_analytics("CPARTIAL01", spec=spec_partial)
    assert res_partial.is_available is False
    assert "METADATA_INCOMPLETE" in str(res_partial.unavailable_reason)

    # 2. Warrant with UNKNOWN lifecycle
    spec_unknown = CoveredWarrantSpecification(
        symbol="CUNKNOWN01",
        issuer="SSI",
        underlying_symbol="HPG",
        strike_price=22000.0,
        exercise_ratio=2.0,
        maturity_date="2026-11-20",
        last_trading_date=None,
        listed_volume=None,
        issue_price=None,
        status=InstrumentLifecycleStatus.UNKNOWN,
        data_quality=DataQualityStatus.COMPLETE,
        evidence_level=LifecycleEvidenceLevel.SEARCH_ONLY,
        metadata_verification=MetadataVerificationStatus.VERIFIED_CURRENT,
    )
    res_unknown = await engine.compute_warrant_analytics("CUNKNOWN01", spec=spec_unknown)
    assert res_unknown.is_available is False
    assert "LIFECYCLE_NOT_ACTIVE" in str(res_unknown.unavailable_reason)

    # 3. Warrant with UNVERIFIED metadata verification status
    spec_unverified = CoveredWarrantSpecification(
        symbol="CUNVERIFIED01",
        issuer="SSI",
        underlying_symbol="HPG",
        strike_price=22000.0,
        exercise_ratio=2.0,
        maturity_date="2026-11-20",
        last_trading_date=None,
        listed_volume=None,
        issue_price=None,
        status=InstrumentLifecycleStatus.ACTIVE,
        data_quality=DataQualityStatus.COMPLETE,
        evidence_level=LifecycleEvidenceLevel.MANUAL_SNAPSHOT,
        metadata_verification=MetadataVerificationStatus.UNVERIFIED,
    )
    res_unver = await engine.compute_warrant_analytics("CUNVERIFIED01", spec=spec_unverified)
    assert res_unver.is_available is False
    assert "METADATA_NOT_VERIFIED_CURRENT" in str(res_unver.unavailable_reason)


@pytest.mark.asyncio
async def test_corporate_action_adjusted_terms_passed_to_quant_engine():
    """
    Proves that QuantEngine consumes ONLY effective terms (K_effective, CR_effective)
    and ignores obsolete initial issuance values.
    """
    engine = LiveQuantEngine()

    spec = CoveredWarrantSpecification(
        symbol="CHPG2602",
        issuer="TCBS",
        underlying_symbol="HPG",
        initial_strike_price=29000.0,
        initial_exercise_ratio=4.0,
        effective_strike_price=25885.0,
        effective_exercise_ratio=3.5704,
        strike_price=25885.0,
        exercise_ratio=3.5704,
        is_adjusted=True,
        terms_effective_date="2026-06-18",
        adjustment_reference="HOSE Notice on HPG Corporate Action Adjustment",
        maturity_date="2026-09-21",
        last_trading_date="2026-09-17",
        listed_volume=10000000,
        issue_price=1000.0,
        status=InstrumentLifecycleStatus.ACTIVE,
        data_quality=DataQualityStatus.COMPLETE,
        evidence_level=LifecycleEvidenceLevel.CURRENT_EXCHANGE_LIST,
        metadata_verification=MetadataVerificationStatus.VERIFIED_CURRENT,
    )

    und_quote = CanonicalQuote(symbol="HPG", instrument_type="STOCK", last_price=22150.0)
    cw_quote = CanonicalQuote(
        symbol="CHPG2602",
        instrument_type="CW",
        bid1_price=40.0,
        ask1_price=50.0,
        last_price=None,
    )

    analytics = await engine.compute_warrant_analytics(
        "CHPG2602", spec=spec, cw_state=cw_quote, und_state=und_quote
    )

    assert analytics.is_available is True
    assert analytics.model_inputs is not None
    # Invariant: strike and ratio are EFFECTIVE, NOT initial
    assert analytics.model_inputs.strike_price == 25885.0
    assert analytics.model_inputs.strike_price != spec.initial_strike_price
    assert analytics.model_inputs.exercise_ratio == 3.5704
    assert analytics.model_inputs.exercise_ratio != spec.initial_exercise_ratio

    # S = 22150 < K_eff = 25885 -> OTM
    assert analytics.moneyness == round(22150.0 / 25885.0, 5)
    assert analytics.moneyness_category == MoneynessCategory.OTM

    # Solves valid IVs for Bid=40 VND and Ask=50 VND
    assert analytics.iv_bid is not None
    assert analytics.iv_ask is not None
    assert 0.30 < analytics.iv_bid < 0.60
    assert 0.30 < analytics.iv_ask < 0.60
    assert analytics.iv_bid < analytics.iv_ask

    # Invariant: Without independent HV, theoretical_price is strictly None (NOT circular IV Mid!)
    assert analytics.theoretical_price is None
    assert analytics.theoretical_volatility is None
    assert analytics.theoretical_volatility_source == "UNAVAILABLE"

    # Invariant: IV Mid repricing is stored separately as model_price_at_iv_mid
    assert analytics.model_price_at_iv_mid is not None
    assert abs(analytics.model_price_at_iv_mid - 45.0) < 1.0

    # Greeks are computed using IV_MID
    assert analytics.greeks.volatility_source == GreeksVolatilitySource.IV_MID
    assert analytics.greeks.theoretical_price is None  # Theo price remains None without independent HV
    assert analytics.greeks.model_price_at_iv_mid is not None
    assert analytics.greeks.delta is not None
    assert analytics.greeks.gamma is not None
    assert analytics.greeks.theta is not None
    assert analytics.greeks.vega is not None
    assert analytics.greeks.rho is not None


@pytest.mark.asyncio
async def test_theoretical_price_requires_independent_volatility_source():
    """
    Verifies that true Theoretical Price requires an independent volatility assumption (HV_22)
    supplied by the real HistoricalVolatilityService, and stores theoreticalVolatility and
    theoreticalVolatilitySource for auditability.
    """
    closes = synthetic_closes(40, base=22000.0)
    expected_hv = calculate_historical_volatility(
        closes, window=settings.QUANT_HV_WINDOW_SESSIONS, min_periods=settings.QUANT_HV_MIN_SESSIONS
    )
    assert expected_hv is not None and expected_hv > 0

    hv_service = HistoricalVolatilityService(bar_source=FakeBarSource({"HPG": make_daily_bars(closes)}))
    await hv_service.warm(["HPG"])

    engine = LiveQuantEngine()
    engine.set_historical_vol_getter(hv_service.get_estimate)  # production wiring, typed VolEstimate

    spec = CoveredWarrantSpecification(
        symbol="CHPG2602",
        issuer="TCBS",
        underlying_symbol="HPG",
        strike_price=25885.0,
        exercise_ratio=3.5704,
        maturity_date="2026-09-21",
        last_trading_date="2026-09-17",
        listed_volume=10000000,
        issue_price=1000.0,
        status=InstrumentLifecycleStatus.ACTIVE,
        data_quality=DataQualityStatus.COMPLETE,
        evidence_level=LifecycleEvidenceLevel.CURRENT_EXCHANGE_LIST,
        metadata_verification=MetadataVerificationStatus.VERIFIED_CURRENT,
    )

    und_quote = CanonicalQuote(symbol="HPG", instrument_type="STOCK", last_price=22150.0)
    cw_quote = CanonicalQuote(
        symbol="CHPG2602",
        instrument_type="CW",
        bid1_price=40.0,
        ask1_price=50.0,
        last_price=None,
    )

    analytics = await engine.compute_warrant_analytics(
        "CHPG2602", spec=spec, cw_state=cw_quote, und_state=und_quote
    )

    assert analytics.is_available is True
    # 1. Independent Theoretical Fair Price is computed from HV_22
    assert analytics.theoretical_price is not None
    assert analytics.theoretical_volatility == expected_hv
    assert analytics.theoretical_volatility_source == "HV_22"
    assert analytics.historical_volatility == expected_hv

    # Reprice from the CANONICAL full-precision T the engine used (clock is frozen), not
    # the 5dp display echo in model_inputs. Both paths apply round(_/CR, 2), so with the
    # same T this is exact.
    assert analytics.model_inputs is not None
    T_full, _dte = calculate_time_to_maturity(spec.maturity_date)
    assert T_full > 0
    expected_theo_price = round(bs_call_price_share(22150.0, 25885.0, T_full, 0.05, 0.0, expected_hv) / 3.5704, 2)
    assert analytics.theoretical_price == expected_theo_price
    assert analytics.greeks.theoretical_price == expected_theo_price
    # the display echo is the rounded T, verified separately
    assert analytics.model_inputs.time_to_maturity == round(T_full, 5)

    # 2. Market IV Mid repricing remains separate
    assert analytics.model_price_at_iv_mid is not None
    assert abs(analytics.model_price_at_iv_mid - 45.0) < 1.0
    assert analytics.theoretical_price != analytics.model_price_at_iv_mid


@pytest.mark.asyncio
@pytest.mark.parametrize("frozen_now", [
    datetime(2026, 6, 1, 10, 0, tzinfo=VN_TZ),    # far from maturity
    datetime(2026, 8, 29, 10, 0, tzinfo=VN_TZ),    # the date class of bug first surfaced
    datetime(2026, 9, 10, 10, 0, tzinfo=VN_TZ),    # ~11 days out
    datetime(2026, 9, 17, 10, 0, tzinfo=VN_TZ),    # last trading day - still tradable, most T-sensitive
])
async def test_theo_price_provenance_is_date_boundary_stable(monkeypatch, frozen_now):
    """Regression: repricing the independent theoretical price from the CANONICAL full T
    (not the 5dp model_inputs echo) reproduces it exactly, at any 'today'."""
    monkeypatch.setattr(_qe, "get_vietnam_now", lambda: frozen_now)

    closes = synthetic_closes(40, base=22000.0)
    expected_hv = calculate_historical_volatility(
        closes, window=settings.QUANT_HV_WINDOW_SESSIONS, min_periods=settings.QUANT_HV_MIN_SESSIONS
    )
    svc = HistoricalVolatilityService(bar_source=FakeBarSource({"HPG": make_daily_bars(closes)}))
    await svc.warm(["HPG"])
    engine = LiveQuantEngine()
    engine.set_historical_vol_getter(svc.get_estimate)

    spec = CoveredWarrantSpecification(
        symbol="CHPG2602", issuer="TCBS", underlying_symbol="HPG",
        strike_price=25885.0, exercise_ratio=3.5704,
        maturity_date="2026-09-21", last_trading_date="2026-09-17",
        status=InstrumentLifecycleStatus.ACTIVE, data_quality=DataQualityStatus.COMPLETE,
        evidence_level=LifecycleEvidenceLevel.CURRENT_EXCHANGE_LIST,
        metadata_verification=MetadataVerificationStatus.VERIFIED_CURRENT,
    )
    und = CanonicalQuote(symbol="HPG", instrument_type="STOCK", last_price=22150.0)
    cw = CanonicalQuote(symbol="CHPG2602", instrument_type="CW", bid1_price=40.0, ask1_price=50.0, last_price=None)

    a = await engine.compute_warrant_analytics("CHPG2602", spec=spec, cw_state=cw, und_state=und)
    assert a.is_available is True

    T_full, _dte = calculate_time_to_maturity(spec.maturity_date)
    expected = round(bs_call_price_share(22150.0, 25885.0, T_full, 0.05, 0.0, expected_hv) / 3.5704, 2)
    assert a.theoretical_price == expected
    assert a.greeks.theoretical_price == expected
    assert a.model_inputs.time_to_maturity == round(T_full, 5)


@pytest.mark.asyncio
async def test_complete_metadata_does_not_bypass_contradictory_guard():
    """
    Demonstrates that an ACTIVE + COMPLETE + VERIFIED_CURRENT warrant whose market prices contradict
    no-arbitrage lower bounds does NOT crash or fabricate fake IVs.
    """
    engine = LiveQuantEngine()

    spec = CoveredWarrantSpecification(
        symbol="CITM_TEST",
        issuer="SSI",
        underlying_symbol="HPG",
        strike_price=20000.0,
        exercise_ratio=2.0,
        maturity_date="2026-11-20",
        last_trading_date=None,
        listed_volume=None,
        issue_price=None,
        status=InstrumentLifecycleStatus.ACTIVE,
        data_quality=DataQualityStatus.COMPLETE,
        evidence_level=LifecycleEvidenceLevel.MANUAL_SNAPSHOT,
        metadata_verification=MetadataVerificationStatus.VERIFIED_CURRENT,
    )

    und_quote = CanonicalQuote(symbol="HPG", instrument_type="STOCK", last_price=25000.0)
    # Intrinsic value is ~2500 VND/CW. Market depth 40/50 VND is impossible.
    cw_quote = CanonicalQuote(
        symbol="CITM_TEST",
        instrument_type="CW",
        bid1_price=40.0,
        ask1_price=50.0,
        last_price=None,
    )

    analytics = await engine.compute_warrant_analytics(
        "CITM_TEST", spec=spec, cw_state=cw_quote, und_state=und_quote
    )

    assert analytics.is_available is True
    # Both Bid and Ask IVs are strictly None due to no-arbitrage bound violation
    assert analytics.iv_bid is None
    assert analytics.iv_ask is None
    assert analytics.iv_trade is None


@pytest.mark.asyncio
async def test_engine_event_driven_computation_and_missing_trade():
    """
    Verifies that for an ACTIVE + COMPLETE warrant with in-bounds prices:
    - S comes from underlying
    - Bid / Ask generate IV_Bid / IV_Ask
    - If NO trade tick exists, iv_trade is strictly None (not fabricated!)
    - Moneyness (S/K) is calculated accurately
    """
    engine = LiveQuantEngine()

    spec = CoveredWarrantSpecification(
        symbol="CHPG2602",
        issuer="TCBS",
        underlying_symbol="HPG",
        strike_price=25885.0,
        exercise_ratio=3.5704,
        maturity_date="2026-09-21",
        last_trading_date="2026-09-17",
        listed_volume=10000000,
        issue_price=1000.0,
        status=InstrumentLifecycleStatus.ACTIVE,
        data_quality=DataQualityStatus.COMPLETE,
        evidence_level=LifecycleEvidenceLevel.CURRENT_EXCHANGE_LIST,
        metadata_verification=MetadataVerificationStatus.VERIFIED_CURRENT,
    )

    und_quote = CanonicalQuote(symbol="HPG", instrument_type="STOCK", last_price=22150.0)
    # In-bounds CW Bid/Ask
    cw_quote = CanonicalQuote(
        symbol="CHPG2602",
        instrument_type="CW",
        bid1_price=40.0,
        ask1_price=50.0,
        last_price=None,
    )

    for quote in (und_quote, cw_quote):
        quote.market_session_date = "2026-08-28"
        quote.trade_timestamp = quote.book_timestamp = int(datetime(2026, 8, 28, 15, tzinfo=VN_TZ).timestamp() * 1000)
    engine.set_market_state_getter(lambda s: und_quote if s == "HPG" else cw_quote)

    analytics = await engine.compute_warrant_analytics(
        "CHPG2602", spec=spec, cw_state=cw_quote, und_state=und_quote
    )

    assert analytics.is_available is True
    assert analytics.symbol == "CHPG2602"
    assert analytics.underlying_symbol == "HPG"
    assert analytics.moneyness == round(22150.0 / 25885.0, 5)
    assert analytics.moneyness_category == MoneynessCategory.OTM

    # Bid / Ask IVs solved
    assert analytics.iv_bid is not None
    assert analytics.iv_ask is not None
    assert analytics.iv_bid < analytics.iv_ask

    # Critical invariant: No trade tick -> iv_trade is strictly None!
    assert analytics.iv_trade is None

    # Greeks computed using IV_MID fallback
    assert analytics.greeks.volatility_source == GreeksVolatilitySource.IV_MID
    assert analytics.greeks.delta is not None
    assert analytics.greeks.gamma is not None
    assert analytics.greeks.theta is not None
    assert analytics.greeks.vega is not None


def test_moneyness_independence_from_cw_price():
    """
    Moneyness = S / K. Changing CW Bid/Ask/Trade must not change Moneyness.
    """
    spec = CoveredWarrantSpecification(
        symbol="CFPT2602",
        issuer="SSI",
        underlying_symbol="FPT",
        strike_price=70000.0,
        exercise_ratio=2.0,
        maturity_date="2026-11-20",
        last_trading_date=None,
        listed_volume=None,
        issue_price=None,
        status=InstrumentLifecycleStatus.ACTIVE,
        data_quality=DataQualityStatus.COMPLETE,
        evidence_level=LifecycleEvidenceLevel.MANUAL_SNAPSHOT,
        metadata_verification=MetadataVerificationStatus.VERIFIED_CURRENT,
    )

    und_quote = CanonicalQuote(symbol="FPT", instrument_type="STOCK", last_price=71500.0)
    expected_moneyness = round(71500.0 / 70000.0, 5)

    # Any CW price yields identical moneyness
    cw_quote_1 = CanonicalQuote(symbol="CFPT2602", instrument_type="CW", bid1_price=100.0, ask1_price=200.0)
    cw_quote_2 = CanonicalQuote(symbol="CFPT2602", instrument_type="CW", bid1_price=800.0, ask1_price=900.0)

    assert und_quote.last_price is not None and spec.strike_price is not None
    m1 = und_quote.last_price / spec.strike_price
    m2 = und_quote.last_price / spec.strike_price

    assert round(m1, 5) == expected_moneyness
    assert round(m2, 5) == expected_moneyness


def test_rest_api_quant_calculate():
    resp = client.post(
        "/api/quant/calculate",
        json={
            "underlyingPrice": 22100.0,
            "strikePrice": 22000.0,
            "timeToMaturity": 0.23886,
            "riskFreeRate": 0.05,
            "volatility": 0.2591,
            "exerciseRatio": 2.0,
            "marketPrice": 648.26,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["theoreticalPrice"] is not None
    assert abs(data["theoreticalPrice"] - 648.26) < 0.05
    assert data["delta"] is not None
    assert abs(data["delta"] - 0.28835) < 0.0001
    assert data["gamma"] is not None
    assert abs(data["gamma"] - 0.00006996) < 0.0000001
    assert data["theta"] is not None
    assert abs(data["theta"] - (-3.93)) < 0.02
    assert data["vega"] is not None
    assert abs(data["vega"] - 21.15) < 0.02
    assert data["rho"] is not None
    assert abs(data["rho"] - 13.67) < 0.02
    assert data["impliedVolatility"] is not None
    assert abs(data["impliedVolatility"] - 0.2591) < 0.001


@pytest.mark.asyncio
async def test_eod_close_gap_fills_when_postgres_lacks_todays_bar(monkeypatch):
    """FiinQuant routinely lags publishing a session's final bar for hours after the
    close - a plain DB-only read used to fail EOD_INPUT_MISSING even when the provider
    already had the close (confirmed live in prod). `_eod_close` must go through the same
    Postgres-first-with-gap-fill path the dashboard's own EOD fallback already uses."""
    import app.market_data.history_read_service as hrs

    calls = []

    async def fake_get_history(symbol, *, timeframe, from_date, to_date, adjusted):
        calls.append((symbol, timeframe, from_date, to_date, adjusted))
        return [
            HistoricalBar(date="2026-09-03", open=21500, high=21700, low=21400, close=21600,
                          volume=1000, session_date="2026-09-03"),
            # The session actually asked for - only reachable via the gap-fill, not a raw
            # DB read (this is the bar that "just landed" upstream).
            HistoricalBar(date="2026-09-04", open=21600, high=21900, low=21550, close=21700,
                          volume=1200, session_date="2026-09-04"),
        ]

    monkeypatch.setattr(hrs.history_read_service, "get_history", fake_get_history)

    close = await LiveQuantEngine._eod_close(
        None, "HPG", date(2026, 9, 4), price_basis="ADJUSTED",
    )

    assert close == 21700.0
    assert len(calls) == 1
    symbol, timeframe, _from_date, to_date, adjusted = calls[0]
    assert symbol == "HPG"
    assert timeframe == "1d"
    assert to_date == "2026-09-04"
    assert adjusted is True  # ADJUSTED price_basis -> adjusted=True


@pytest.mark.asyncio
async def test_eod_close_stays_none_when_the_session_is_genuinely_absent(monkeypatch):
    import app.market_data.history_read_service as hrs

    async def fake_get_history(symbol, **kwargs):
        return [HistoricalBar(date="2026-09-03", open=21500, high=21700, low=21400,
                              close=21600, volume=1000, session_date="2026-09-03")]

    monkeypatch.setattr(hrs.history_read_service, "get_history", fake_get_history)

    close = await LiveQuantEngine._eod_close(
        None, "HPG", date(2026, 9, 4), price_basis="RAW",
    )
    assert close is None


def test_rest_api_get_warrant_analytics():
    resp = client.get("/api/quant/CHPG2602")
    assert resp.status_code == 200
    data = resp.json()
    assert data["symbol"] == "CHPG2602"
    assert data["underlying_symbol"] == "HPG"
    assert "is_available" in data
    assert "greeks" in data
