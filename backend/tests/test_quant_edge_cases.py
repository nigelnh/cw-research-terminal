"""
Edge-case behavior of the production Black-Scholes primitives.

Every case asserts an EXPLICIT outcome: a valid value, a controlled zero/None,
or a defined diagnostic string. Nothing may return NaN / inf / a silent wrong number.

Production contract (app.quant.black_scholes):
  bs_call_price_share:
    S<=0 | K<=0 | sigma<=0  -> 0.0
    T<=0                    -> max(0, S - K)
  calculate_analytical_greeks:
    S<=0 | K<=0 | exercise_ratio<=0 -> WarrantGreeks(all None, source UNAVAILABLE)
    T<=0                            -> intrinsic branch (price=intrinsic/k, delta=1/k or 0, others 0)
    sigma clamped to [1e-4, 10.0]
  solve_implied_volatility:
    S<=0 | K<=0 | T<=0 | market_price_cw<=0 | exercise_ratio<=0 -> (None, "INVALID_INPUT")
"""

import math

import pytest

from app.quant.black_scholes import (
    bs_call_price_share,
    calculate_analytical_greeks,
    solve_implied_volatility,
)
from app.quant.quant_schemas import GreeksVolatilitySource

R = 0.05


def _finite(x):
    return x is not None and math.isfinite(x)


# --------------------------------------------------------------------------- #
# Near expiry
# --------------------------------------------------------------------------- #
def test_near_expiry_positive_T_is_finite_and_near_intrinsic():
    S, K, k = 30500.0, 30000.0, 2.0
    T = 1e-5
    price = bs_call_price_share(S, K, T, R, 0.0, 0.30)
    assert _finite(price)
    assert price == pytest.approx(S - K, abs=5.0)          # time value ~ 0

    g = calculate_analytical_greeks(S, K, T, R, 0.0, 0.30, exercise_ratio=k)
    assert all(_finite(v) for v in (g.theoretical_price, g.delta, g.gamma, g.theta, g.vega, g.rho))
    assert g.delta == pytest.approx(1.0 / k, abs=0.05)     # ITM -> delta ~ 1/k
    assert g.theoretical_price == pytest.approx((S - K) / k, abs=3.0)


def test_T_exactly_zero_returns_intrinsic():
    for S, K, exp_delta in ((32000.0, 30000.0, 0.5), (28000.0, 30000.0, 0.0)):
        k = 2.0
        assert bs_call_price_share(S, K, 0.0, R, 0.0, 0.30) == max(0.0, S - K)
        g = calculate_analytical_greeks(S, K, 0.0, R, 0.0, 0.30, exercise_ratio=k)
        assert g.theoretical_price == pytest.approx(max(0.0, S - K) / k, abs=1e-9)
        assert g.delta == pytest.approx(exp_delta if S > K else 0.0, abs=1e-9)
        assert g.gamma == 0.0 and g.theta == 0.0 and g.vega == 0.0 and g.rho == 0.0


def test_negative_T_treated_as_expired():
    assert bs_call_price_share(31000.0, 30000.0, -0.5, R, 0.0, 0.30) == 1000.0
    g = calculate_analytical_greeks(31000.0, 30000.0, -0.5, R, 0.0, 0.30, exercise_ratio=1.0)
    assert g.theoretical_price == 1000.0
    sigma, reason = solve_implied_volatility(31000.0, 30000.0, -0.5, R, 0.0, 500.0, exercise_ratio=1.0)
    assert sigma is None and reason == "INVALID_INPUT"


# --------------------------------------------------------------------------- #
# Deep moneyness
# --------------------------------------------------------------------------- #
def test_deep_itm_limits():
    S, K, T, k = 100000.0, 20000.0, 0.5, 4.0
    g = calculate_analytical_greeks(S, K, T, R, 0.0, 0.25, exercise_ratio=k)
    assert g.delta == pytest.approx(1.0 / k, abs=1e-4)
    assert g.gamma == pytest.approx(0.0, abs=1e-9)
    assert g.vega == pytest.approx(0.0, abs=1e-2)
    # price -> (S - K e^{-rT}) / k
    assert g.theoretical_price == pytest.approx((S - K * math.exp(-R * T)) / k, abs=1.0)


def test_deep_otm_limits():
    S, K, T, k = 4000.0, 40000.0, 0.2, 1.0
    assert bs_call_price_share(S, K, T, R, 0.0, 0.30) == pytest.approx(0.0, abs=1e-6)
    g = calculate_analytical_greeks(S, K, T, R, 0.0, 0.30, exercise_ratio=k)
    assert g.theoretical_price == pytest.approx(0.0, abs=1e-6)
    assert g.delta == pytest.approx(0.0, abs=1e-6)
    assert g.gamma == pytest.approx(0.0, abs=1e-9)
    assert g.vega == pytest.approx(0.0, abs=1e-6)


# --------------------------------------------------------------------------- #
# Volatility extremes / clamping
# --------------------------------------------------------------------------- #
def test_zero_and_ultra_low_vol_no_division_by_zero():
    S, K, T, k = 30000.0, 30000.0, 0.5, 2.0
    # sigma <= 0 -> pricer returns 0.0 by contract
    assert bs_call_price_share(S, K, T, R, 0.0, 0.0) == 0.0
    assert bs_call_price_share(S, K, T, R, 0.0, -0.1) == 0.0
    # greeks clamp sigma to 1e-4 -> finite, ~ discounted intrinsic (ATM -> ~0 time value)
    g = calculate_analytical_greeks(S, K, T, R, 0.0, 1e-9, exercise_ratio=k)
    assert all(_finite(v) for v in (g.theoretical_price, g.delta, g.gamma, g.theta, g.vega, g.rho))
    assert g.gamma is not None and g.gamma >= 0.0
    assert g.vega is not None and g.vega >= 0.0
    g_clamped = calculate_analytical_greeks(S, K, T, R, 0.0, 1e-4, exercise_ratio=k)
    assert g.theoretical_price == pytest.approx(g_clamped.theoretical_price, abs=1e-6)


def test_high_and_over_range_vol_are_finite_and_clamped():
    S, K, T, k = 25000.0, 25000.0, 0.5, 2.0
    for sigma in (5.0, 10.0, 15.0, 50.0):
        g = calculate_analytical_greeks(S, K, T, R, 0.0, sigma, exercise_ratio=k)
        assert all(_finite(v) for v in (g.theoretical_price, g.delta, g.gamma, g.theta, g.vega, g.rho))
        assert g.delta is not None and 0.0 <= g.delta <= 1.0 / k + 1e-9
        assert g.gamma is not None and g.gamma >= 0.0
        assert g.vega is not None and g.vega >= 0.0
        assert g.volatility_used is not None and g.volatility_used <= 10.0 + 1e-9
    # sigma above the clamp collapses onto the sigma=10 result
    a = calculate_analytical_greeks(S, K, T, R, 0.0, 15.0, exercise_ratio=k)
    b = calculate_analytical_greeks(S, K, T, R, 0.0, 10.0, exercise_ratio=k)
    assert a.theoretical_price == pytest.approx(b.theoretical_price, abs=1e-6)


# --------------------------------------------------------------------------- #
# Dividend on / off
# --------------------------------------------------------------------------- #
def test_zero_vs_positive_dividend_behaviour():
    S, K, T, k = 30000.0, 30000.0, 1.0, 1.0
    g0 = calculate_analytical_greeks(S, K, T, R, 0.0, 0.30, exercise_ratio=k)
    gq = calculate_analytical_greeks(S, K, T, R, 0.05, 0.30, exercise_ratio=k)
    assert g0.theoretical_price is not None and gq.theoretical_price is not None
    assert gq.theoretical_price < g0.theoretical_price          # dividend lowers a call
    assert g0.delta is not None and gq.delta is not None and gq.delta < g0.delta
    # gamma / vega stay non-negative and finite under q
    assert gq.gamma is not None and gq.gamma >= 0.0
    assert gq.vega is not None and gq.vega >= 0.0


# --------------------------------------------------------------------------- #
# Invalid financial inputs -> controlled, not fabricated zeros
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("S,K", [(0.0, 25000.0), (-1.0, 25000.0), (25000.0, 0.0), (25000.0, -5.0)])
def test_invalid_spot_or_strike_price_primitive_returns_zero(S, K):
    assert bs_call_price_share(S, K, 0.5, R, 0.0, 0.30) == 0.0


@pytest.mark.parametrize("S,K,k", [(0.0, 25000.0, 2.0), (25000.0, 0.0, 2.0), (25000.0, 25000.0, 0.0), (25000.0, 25000.0, -1.0)])
def test_invalid_inputs_greeks_are_all_none_and_unavailable(S, K, k):
    g = calculate_analytical_greeks(S, K, 0.5, R, 0.0, 0.30, exercise_ratio=k)
    assert g.delta is None and g.gamma is None and g.theta is None and g.vega is None and g.rho is None
    assert g.theoretical_price is None
    assert g.volatility_source == GreeksVolatilitySource.UNAVAILABLE


@pytest.mark.parametrize(
    "S,K,T,mp,k,expected",
    [
        (0.0, 25000.0, 0.5, 100.0, 1.0, "INVALID_INPUT"),
        (25000.0, 0.0, 0.5, 100.0, 1.0, "INVALID_INPUT"),
        (25000.0, 25000.0, 0.0, 100.0, 1.0, "INVALID_INPUT"),
        (25000.0, 25000.0, 0.5, 0.0, 1.0, "INVALID_INPUT"),
        (25000.0, 25000.0, 0.5, -1.0, 1.0, "INVALID_INPUT"),
        (25000.0, 25000.0, 0.5, 100.0, 0.0, "INVALID_INPUT"),
    ],
)
def test_iv_solver_invalid_inputs_diagnostics(S, K, T, mp, k, expected):
    sigma, reason = solve_implied_volatility(S, K, T, R, 0.0, mp, exercise_ratio=k)
    assert sigma is None
    assert reason == expected
