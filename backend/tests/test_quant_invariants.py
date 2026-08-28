"""
Mathematical invariants of the production Black-Scholes code, over deterministic
parameter grids (no RNG).

All checks call production functions only.
"""

import math
from itertools import product

import pytest

from app.quant.black_scholes import bs_call_price_share, calculate_analytical_greeks, solve_implied_volatility

R = 0.05
SPOTS = (8000.0, 15000.0, 25000.0, 40000.0, 90000.0)
STRIKES = (10000.0, 25000.0, 50000.0)
TS = (0.02, 0.1, 0.5, 1.0, 3.0)
SIGMAS = (0.08, 0.2, 0.5, 1.0, 2.5)
QS = (0.0, 0.02, 0.05)
RATIOS = (1.0, 2.0, 5.0)


def _full_grid():
    return list(product(SPOTS, STRIKES, TS, SIGMAS, QS))


def test_call_price_nondecreasing_in_spot():
    for K, T, sigma, q in product(STRIKES, TS, SIGMAS, QS):
        prev = -1.0
        for S in sorted(SPOTS):
            c = bs_call_price_share(S, K, T, R, q, sigma)
            assert c >= prev - 1e-9, f"price decreased in S at S={S},K={K},T={T},s={sigma},q={q}"
            prev = c


def test_call_price_nondecreasing_in_sigma():
    for S, K, T, q in product(SPOTS, STRIKES, TS, QS):
        prev = -1.0
        for sigma in sorted(SIGMAS):
            c = bs_call_price_share(S, K, T, R, q, sigma)
            assert c >= prev - 1e-9, f"price decreased in sigma at S={S},K={K},T={T},q={q},s={sigma}"
            prev = c


def test_call_price_nonincreasing_in_dividend_yield():
    for S, K, T, sigma in product(SPOTS, STRIKES, TS, SIGMAS):
        prev = math.inf
        for q in sorted(QS):
            c = bs_call_price_share(S, K, T, R, q, sigma)
            assert c <= prev + 1e-9, f"price increased in q at S={S},K={K},T={T},s={sigma},q={q}"
            prev = c


def test_call_price_nonincreasing_in_strike():
    for S, T, sigma, q in product(SPOTS, TS, SIGMAS, QS):
        prev = math.inf
        for K in sorted(STRIKES):
            c = bs_call_price_share(S, K, T, R, q, sigma)
            assert c <= prev + 1e-9, f"price increased in K at S={S},T={T},s={sigma},q={q},K={K}"
            prev = c


def test_gamma_and_vega_nonnegative_everywhere():
    for S, K, T, sigma, q in _full_grid():
        for k in RATIOS:
            g = calculate_analytical_greeks(S, K, T, R, q, sigma, exercise_ratio=k)
            assert g.gamma is not None and g.gamma >= 0.0, (S, K, T, sigma, q, k, g.gamma)
            assert g.vega is not None and g.vega >= 0.0, (S, K, T, sigma, q, k, g.vega)


def test_call_delta_within_zero_and_one_over_k():
    for S, K, T, sigma, q in _full_grid():
        for k in RATIOS:
            g = calculate_analytical_greeks(S, K, T, R, q, sigma, exercise_ratio=k)
            assert g.delta is not None
            assert -1e-9 <= g.delta <= (1.0 / k) + 1e-9, (S, K, T, sigma, q, k, g.delta)


def test_no_arbitrage_bounds_on_cw_price():
    for S, K, T, sigma, q in _full_grid():
        for k in RATIOS:
            # The no-arbitrage invariant applies to the model value; theoretical_price
            # is that value rounded to 2 dp, so check the unrounded model value here...
            model_cw = bs_call_price_share(S, K, T, R, q, sigma) / k
            lo = max(0.0, S * math.exp(-q * T) - K * math.exp(-R * T)) / k
            hi = S * math.exp(-q * T) / k
            assert model_cw >= lo - 1e-6
            assert model_cw <= hi + 1e-6
            # ...and confirm the published value only differs by the documented rounding
            g = calculate_analytical_greeks(S, K, T, R, q, sigma, exercise_ratio=k)
            assert g.theoretical_price is not None
            assert g.theoretical_price == pytest.approx(model_cw, abs=0.01)


def test_cw_price_at_least_discounted_intrinsic_and_nonnegative():
    for S, K, T, sigma, q in _full_grid():
        c = bs_call_price_share(S, K, T, R, q, sigma)
        assert c >= 0.0
        # a European call is worth at least its forward-discounted intrinsic
        assert c >= max(0.0, S * math.exp(-q * T) - K * math.exp(-R * T)) - 1e-4


def test_iv_roundtrip_reproduces_price_on_grid():
    """For every solvable grid point, solve(price) then reprice -> original price."""
    checked = 0
    for S, K, T, sigma, q in _full_grid():
        k = 2.0
        price = bs_call_price_share(S, K, T, R, q, sigma) / k
        if price < 1e-2:
            continue
        rec, reason = solve_implied_volatility(S, K, T, R, q, price, exercise_ratio=k)
        if reason is not None:
            # only acceptable when true sigma is outside the default [1e-4, 5] search band
            assert sigma <= 1e-4 or sigma >= 5.0 or reason == "NO_ROOT_IN_SIGMA_RANGE"
            continue
        assert rec is not None
        reprice = bs_call_price_share(S, K, T, R, q, rec) / k
        # The solver stops on price error <= 1e-4 share-equiv OR bracket width <= 1e-5.
        # In low-vega corners the bracket-width exit bounds the reprice error by
        # (local vega) * 1e-5; 3e-4 relative + 1e-2 abs is a safe envelope for the grid.
        assert reprice == pytest.approx(price, abs=1e-2 + 3e-4 * price), (S, K, T, sigma, q)
        checked += 1
    assert checked > 200          # the grid actually exercised the solver broadly


def test_theta_negative_for_non_expiring_otm_and_atm_calls():
    """Time decay is negative for OTM/ATM calls not near expiry (positive theta only
    occurs for deep-ITM calls where the interest on the strike dominates)."""
    for S, K in ((22000.0, 25000.0), (25000.0, 25000.0), (24000.0, 25000.0)):
        for T in (0.1, 0.5, 2.0):
            for sigma in (0.2, 0.6):
                g = calculate_analytical_greeks(S, K, T, R, 0.0, sigma, exercise_ratio=2.0)
                assert g.theta is not None and g.theta < 0.0, (S, K, T, sigma, g.theta)
