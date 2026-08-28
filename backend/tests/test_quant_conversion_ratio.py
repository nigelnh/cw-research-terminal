"""
Covered-warrant conversion-ratio scaling verification.

The platform quotes a Covered Warrant, not a plain option. HOSE convention:
    k = number of warrants that convert to 1 underlying share
    -> each warrant carries 1/k of a share
    -> CW quoted price  = per-share Black-Scholes value / k
    -> CW Greeks         = per-share Greeks / k        (per warrant, NOT per share, NOT position-scaled)
    -> the division by k happens ONCE, at the CW level, and rounding is applied AFTER it.

Production under test:
    calculate_analytical_greeks(..., exercise_ratio=k)
    solve_implied_volatility(..., market_price_cw=..., exercise_ratio=k)

These tests fail if the ratio is applied in the wrong direction, applied twice, or
not applied to a Greek.
"""

import pytest

from app.quant.black_scholes import (
    bs_call_price_share,
    calculate_analytical_greeks,
    solve_implied_volatility,
)
from tests.quant_reference import ref_bs_greeks_closed_form

# A single, unambiguous scenario used across the ratio tests.
S, K, T, R, Q, SIGMA = 30000.0, 28000.0, 0.5, 0.05, 0.0, 0.35
CALL_SHARE = bs_call_price_share(S, K, T, R, Q, SIGMA)
RATIOS = [1.0, 2.0, 3.5704, 5.0, 8.0]

# Production rounding granularity per field (see calculate_analytical_greeks):
#   price/vega/rho/theta -> 2 dp ;  delta -> 5 dp ;  gamma -> 8 dp
_ROUND = {"price": 1e-2, "delta": 1e-5, "gamma": 1e-8, "vega": 1e-2, "theta": 1e-2, "rho": 1e-2}


@pytest.mark.parametrize("k", RATIOS)
def test_cw_price_is_share_price_divided_by_ratio_once(k):
    g = calculate_analytical_greeks(S, K, T, R, Q, SIGMA, exercise_ratio=k)
    assert g.theoretical_price is not None
    # Exactly / k  (not / k^2, not * k)
    assert g.theoretical_price == pytest.approx(CALL_SHARE / k, abs=0.01)
    if k != 1.0:                                            # /1 and *1 are identical
        assert abs(g.theoretical_price - CALL_SHARE * k) > 1.0          # not multiplied
        assert abs(g.theoretical_price - CALL_SHARE / (k * k)) > 1.0    # not squared


@pytest.mark.parametrize("k", RATIOS)
def test_all_greeks_scale_by_one_over_ratio(k):
    """scaled == independent(ratio=k)   AND   scaled * k == independent(ratio=1).

    Compared against the independent closed-form reference (tests/quant_reference.py),
    not against another production call, so double-rounding cannot mask a bug.
    Tolerances = (production rounding at ratio k) + (a small reference/agreement margin).
    """
    scaled = calculate_analytical_greeks(S, K, T, R, Q, SIGMA, exercise_ratio=k)
    ref_k = ref_bs_greeks_closed_form(S, K, T, R, Q, SIGMA, ratio=k)
    ref_1 = ref_bs_greeks_closed_form(S, K, T, R, Q, SIGMA, ratio=1.0)

    for field in ("delta", "gamma", "vega", "theta", "rho"):
        val = getattr(scaled, field)
        rnd = _ROUND[field]
        # 1. matches the reference computed directly at ratio k
        margin = rnd + (5e-6 if field == "delta" else 1e-9 if field == "gamma" else 5e-3)
        assert val == pytest.approx(ref_k[field], abs=margin), f"{field} at k={k}"
        # 2. multiplying back by k recovers the ratio-1 reference
        assert val * k == pytest.approx(ref_1[field], abs=(rnd * k) + margin), f"{field}*k at k={k}"


def test_ratio_invariant_product_is_constant():
    """C_cw(k) * k is the same per-share value for every k (within 2 dp * k)."""
    for k in RATIOS:
        g = calculate_analytical_greeks(S, K, T, R, Q, SIGMA, exercise_ratio=k)
        assert g.theoretical_price is not None
        assert g.theoretical_price * k == pytest.approx(CALL_SHARE, abs=0.01 * k + 0.05)


def test_ratio_direction_delta_upper_bound_is_one_over_k():
    """A call warrant with ratio k has delta bounded by 1/k, never k.

    Deep ITM so delta_share -> ~1; then delta_cw -> ~1/k.
    """
    for k in (2.0, 4.0, 8.0):
        g = calculate_analytical_greeks(80000.0, 20000.0, 0.5, R, Q, 0.20, exercise_ratio=k)
        assert g.delta is not None
        assert g.delta == pytest.approx(1.0 / k, abs=0.02)
        assert g.delta < 1.0 / k + 1e-6
        assert g.delta < 1.0                      # never exceeds a single share's delta


def test_expiry_intrinsic_scales_by_ratio():
    """At T <= 0 the CW value is max(0, S-K)/k and delta is 1/k (S>K) - ratio applied once."""
    for k in (1.0, 2.0, 5.0):
        g = calculate_analytical_greeks(32000.0, 30000.0, 0.0, R, Q, 0.30, exercise_ratio=k)
        assert g.theoretical_price == pytest.approx(2000.0 / k, abs=1e-9)
        assert g.delta == pytest.approx(1.0 / k, abs=1e-9)
        assert g.gamma == 0.0 and g.theta == 0.0 and g.vega == 0.0


@pytest.mark.parametrize("k", RATIOS)
def test_iv_solver_inverts_the_ratio_consistently(k):
    """Round-trip: sigma -> CW price (= share price / k) -> solver(price, k) -> sigma.

    The solver converts market_price_cw to a share-equivalent by MULTIPLYING by k
    (`market_price_share = market_price_cw * exercise_ratio`). This test fails if it
    divided instead, or ignored k.
    """
    sigma_true = 0.42
    cw_price = bs_call_price_share(S, K, T, R, Q, sigma_true) / k
    sigma_rec, reason = solve_implied_volatility(
        S=S, K=K, T=T, r=R, q=Q, market_price_cw=cw_price, exercise_ratio=k
    )
    assert reason is None
    assert sigma_rec is not None
    assert sigma_rec == pytest.approx(sigma_true, abs=2e-3)


def test_iv_solver_ratio_wrong_direction_would_not_roundtrip():
    """Sanity: feeding the share-equivalent price with ratio=1 recovers sigma; feeding
    the CW price with ratio=1 (i.e. forgetting k) recovers a DIFFERENT sigma. This
    documents that the ratio genuinely participates in the inversion."""
    sigma_true = 0.42
    k = 4.0
    share_price = bs_call_price_share(S, K, T, R, Q, sigma_true)
    cw_price = share_price / k

    sigma_from_share, _ = solve_implied_volatility(S, K, T, R, Q, share_price, exercise_ratio=1.0)
    sigma_from_cw_wrong_k, _ = solve_implied_volatility(S, K, T, R, Q, cw_price, exercise_ratio=1.0)

    assert sigma_from_share == pytest.approx(sigma_true, abs=2e-3)
    assert sigma_from_cw_wrong_k is None or abs(sigma_from_cw_wrong_k - sigma_true) > 0.05
