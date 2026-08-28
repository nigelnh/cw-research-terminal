"""
Implied-volatility solver verification - production solve_implied_volatility only.

    sigma_true --(production bs_call_price_share)--> CW price --(production solver)--> sigma_recovered

Grid is deterministic (no RNG). Failure diagnostics are asserted explicitly; validation
is NOT weakened to make tests green.

Solver contract (app.quant.black_scholes.solve_implied_volatility):
  market_price_cw <= 0 | exercise_ratio <= 0 | S<=0 | K<=0 | T<=0   -> (None, "INVALID_INPUT")
  price outside no-arb bounds                                        -> (None, "PRICE_OUTSIDE_MODEL_BOUNDS")
  price implies sigma outside [sigma_min, sigma_max]                 -> (None, "NO_ROOT_IN_SIGMA_RANGE")
  otherwise bounded bisection on [sigma_min, sigma_max]              -> (round(sigma, 6), None)
"""

import math

import pytest

from app.quant.black_scholes import bs_call_price_share, solve_implied_volatility

R = 0.05
K = 25000.0

MONEYNESS = {"deep_OTM": 0.70, "OTM": 0.90, "ATM": 1.00, "ITM": 1.10, "deep_ITM": 1.50}
MATURITIES = {"very_short": 0.02, "short": 0.10, "medium": 0.5, "long": 2.0}
VOLS = {"low": 0.10, "mid": 0.30, "high": 1.00, "very_high": 2.00}
RATIOS = (1.0, 4.0)
QS = (0.0, 0.03)


def _vega_per_unit(S, T, q, sigma):
    """Rough analytic vega (per 1.00 vol) to detect near-zero-vega regimes."""
    if T <= 0 or sigma <= 0:
        return 0.0
    sqrt_t = math.sqrt(T)
    d1 = (math.log(S / K) + (R - q + 0.5 * sigma * sigma) * T) / (sigma * sqrt_t)
    pdf = math.exp(-0.5 * d1 * d1) / math.sqrt(2 * math.pi)
    return S * math.exp(-q * T) * sqrt_t * pdf


def _grid():
    for mname, m in MONEYNESS.items():
        for tname, T in MATURITIES.items():
            for vname, sigma in VOLS.items():
                for q in QS:
                    for k in RATIOS:
                        yield (f"{mname}/{tname}/{vname}/q{q}/k{k}", m * K, T, q, sigma, k)


@pytest.mark.parametrize("label,S,T,q,sigma_true,k", list(_grid()), ids=[g[0] for g in _grid()])
def test_iv_roundtrip_grid(label, S, T, q, sigma_true, k):
    """Recover sigma_true from a production-generated price.

    Tolerance rationale:
      * The bisection stops when the bracket width <= 1e-5 OR the share-price error
        <= 1e-4 VND. In normal-vega regimes that pins sigma to ~1e-4.
      * Where vega (per 1.00 vol) < 1.0 VND (deep-OTM / very-short-T / low-vol corners),
        a wide sigma band maps to a sub-tolerance price band, so the solver legitimately
        returns *a* sigma within that flat region. There we only require the RECOVERED
        sigma to REPRODUCE THE PRICE (the economically meaningful invariant), not to
        match sigma_true tightly.
    """
    cw_price = bs_call_price_share(S, K, T, R, q, sigma_true) / k

    # An unsolvably-small price is not a round-trip case (solver returns INVALID_INPUT /
    # NO_ROOT by contract); skip - these corners are covered by the dedicated tests below.
    if cw_price < 1e-3:
        pytest.skip(f"price {cw_price:.2e} below solvable floor")

    sigma_rec, reason = solve_implied_volatility(
        S=S, K=K, T=T, r=R, q=q, market_price_cw=cw_price, exercise_ratio=k
    )
    assert reason is None, f"{label}: unexpected diagnostic {reason}"
    assert sigma_rec is not None

    vega = _vega_per_unit(S, T, q, sigma_true)
    if vega >= 1.0:
        assert sigma_rec == pytest.approx(sigma_true, abs=2e-3), f"{label}: vega={vega:.2f}"
    else:
        # low-vega: require price reproduction instead of tight sigma match
        reprice = bs_call_price_share(S, K, T, R, q, sigma_rec) / k
        assert reprice == pytest.approx(cw_price, abs=1e-3 + 1e-4 * cw_price), f"{label}: vega={vega:.3f}"


def test_iv_roundtrip_headline_cases_are_tight():
    """The economically normal cases (ATM/ITM, T >= 1M, vol 10-100%) recover to 1e-3."""
    for m in (0.95, 1.0, 1.08):
        for T in (0.1, 0.5, 1.5):
            for sigma_true in (0.15, 0.35, 0.9):
                for q in (0.0, 0.03):
                    price = bs_call_price_share(m * K, K, T, R, q, sigma_true) / 4.0
                    rec, reason = solve_implied_volatility(m * K, K, T, R, q, price, exercise_ratio=4.0)
                    assert reason is None and rec is not None
                    assert rec == pytest.approx(sigma_true, abs=1e-3)


def test_iv_monotone_in_price():
    """Higher CW price -> higher implied vol (bid < mid < ask)."""
    S, T, k = 26000.0, 0.4, 2.0
    base = bs_call_price_share(S, K, T, R, 0.0, 0.35) / k
    bid, mid, ask = base * 0.92, base, base * 1.08
    iv_bid, _ = solve_implied_volatility(S, K, T, R, 0.0, bid, exercise_ratio=k)
    iv_mid, _ = solve_implied_volatility(S, K, T, R, 0.0, mid, exercise_ratio=k)
    iv_ask, _ = solve_implied_volatility(S, K, T, R, 0.0, ask, exercise_ratio=k)
    assert iv_bid is not None and iv_mid is not None and iv_ask is not None
    assert iv_bid < iv_mid < iv_ask


# --------------------------------------------------------------------------- #
# Failure / boundary behavior - each must be explicit, never NaN / silent
# --------------------------------------------------------------------------- #
def test_iv_arbitrage_violation_above_upper_bound():
    S, T, k = 20000.0, 0.5, 1.0
    upper = S * math.exp(-0.0 * T)                # call cannot exceed the (discounted) spot
    sigma, reason = solve_implied_volatility(S, K, T, R, 0.0, upper * 1.1, exercise_ratio=k)
    assert sigma is None
    assert reason == "PRICE_OUTSIDE_MODEL_BOUNDS"


def test_iv_arbitrage_violation_below_intrinsic():
    S, K_itm, T, k = 30000.0, 20000.0, 0.5, 1.0
    sub_intrinsic = 500.0                         # < discounted intrinsic ~ 9750
    sigma, reason = solve_implied_volatility(S, K_itm, T, R, 0.0, sub_intrinsic, exercise_ratio=k)
    assert sigma is None
    assert reason == "PRICE_OUTSIDE_MODEL_BOUNDS"


@pytest.mark.parametrize(
    "S,K_,T,mp,k",
    [
        (-1.0, 25000.0, 0.5, 100.0, 1.0),
        (25000.0, -1.0, 0.5, 100.0, 1.0),
        (25000.0, 25000.0, 0.0, 100.0, 1.0),
        (25000.0, 25000.0, -0.3, 100.0, 1.0),
        (25000.0, 25000.0, 0.5, 0.0, 1.0),
        (25000.0, 25000.0, 0.5, -5.0, 1.0),
        (25000.0, 25000.0, 0.5, 100.0, 0.0),
        (25000.0, 25000.0, 0.5, 100.0, -2.0),
    ],
)
def test_iv_invalid_inputs_return_invalid(S, K_, T, mp, k):
    sigma, reason = solve_implied_volatility(S, K_, T, R, 0.0, mp, exercise_ratio=k)
    assert sigma is None
    assert reason == "INVALID_INPUT"


def test_iv_no_root_when_true_sigma_exceeds_search_bounds():
    """A price whose implied vol is above sigma_max returns NO_ROOT_IN_SIGMA_RANGE."""
    S, T, k = 25000.0, 0.5, 1.0
    # generate a price at sigma = 0.60 but search only [0.10, 0.30]
    price = bs_call_price_share(S, K, T, R, 0.0, 0.60) / k
    sigma, reason = solve_implied_volatility(
        S, K, T, R, 0.0, price, exercise_ratio=k, sigma_min=0.10, sigma_max=0.30
    )
    assert sigma is None
    assert reason == "NO_ROOT_IN_SIGMA_RANGE"


def test_iv_no_root_when_true_sigma_below_search_bounds():
    S, T, k = 25000.0, 0.5, 1.0
    price = bs_call_price_share(S, K, T, R, 0.0, 0.05) / k
    sigma, reason = solve_implied_volatility(
        S, K, T, R, 0.0, price, exercise_ratio=k, sigma_min=0.20, sigma_max=0.90
    )
    assert sigma is None
    assert reason == "NO_ROOT_IN_SIGMA_RANGE"


def test_iv_endpoint_clamp_below_sigma_min():
    """A price a hair BELOW bs(sigma_min) (within price_tolerance) clamps to sigma_min."""
    S, T, k = 25000.0, 0.5, 1.0
    p_min = bs_call_price_share(S, K, T, R, 0.0, 1e-4) / k
    lo, reason_lo = solve_implied_volatility(
        S, K, T, R, 0.0, p_min - 5e-5, exercise_ratio=k, price_tolerance=1e-4
    )
    assert reason_lo is None
    assert lo == pytest.approx(1e-4, abs=1e-6)


def test_iv_endpoint_clamp_above_sigma_max():
    """A price a hair ABOVE bs(sigma_max) (within price_tolerance) clamps to sigma_max."""
    S, T, k = 25000.0, 0.5, 1.0
    p_max = bs_call_price_share(S, K, T, R, 0.0, 5.0) / k
    hi, reason_hi = solve_implied_volatility(
        S, K, T, R, 0.0, p_max + 5e-5, exercise_ratio=k, price_tolerance=1e-4
    )
    assert reason_hi is None
    assert hi == pytest.approx(5.0, abs=1e-6)


def test_iv_price_at_sigma_min_reprices_even_if_sigma_not_pinned():
    """When the true sigma is at the flat lower tail, the solver returns *a* sigma in
    that flat region that reproduces the price to tolerance - documented behavior,
    not a bug (vega ~ 0 there so sigma is genuinely under-determined by price)."""
    S, T, k = 25000.0, 0.5, 1.0
    p_min = bs_call_price_share(S, K, T, R, 0.0, 1e-4) / k
    sigma, reason = solve_implied_volatility(S, K, T, R, 0.0, p_min, exercise_ratio=k)
    assert reason is None and sigma is not None
    assert 0.0 < sigma < 0.05
    reprice = bs_call_price_share(S, K, T, R, 0.0, sigma) / k
    assert reprice == pytest.approx(p_min, abs=1e-4)


def test_iv_near_zero_vega_deep_otm_short_maturity_is_controlled():
    """Deep-OTM + very short T: vega ~ 0. Solver must return a controlled result,
    never NaN, never an absurd number, and if it returns a sigma it must reprice."""
    S, T, k = 0.5 * K, 0.01, 4.0
    for sigma_true in (0.25, 0.5):
        price = bs_call_price_share(S, K, T, R, 0.0, sigma_true) / k
        if price <= 0.0:
            sigma, reason = solve_implied_volatility(S, K, T, R, 0.0, max(price, 0.0), exercise_ratio=k)
            assert sigma is None and reason in ("INVALID_INPUT", "PRICE_OUTSIDE_MODEL_BOUNDS", "NO_ROOT_IN_SIGMA_RANGE")
            continue
        sigma, reason = solve_implied_volatility(S, K, T, R, 0.0, price, exercise_ratio=k)
        if sigma is not None:
            assert math.isfinite(sigma) and 0.0 < sigma <= 5.0
            reprice = bs_call_price_share(S, K, T, R, 0.0, sigma) / k
            assert reprice == pytest.approx(price, abs=1e-3 + 1e-3 * price)
        else:
            assert reason in ("NO_ROOT_IN_SIGMA_RANGE", "PRICE_OUTSIDE_MODEL_BOUNDS")


def test_iv_solver_result_is_rounded_to_six_dp():
    S, T, k = 24000.0, 0.4, 2.0
    price = bs_call_price_share(S, K, T, R, 0.0, 0.372183) / k
    sigma, reason = solve_implied_volatility(S, K, T, R, 0.0, price, exercise_ratio=k)
    assert reason is None and sigma is not None
    assert sigma == round(sigma, 6)
