"""
Black-Scholes core verification against INDEPENDENT references.

Production under test:  app.quant.black_scholes
  - bs_call_price_share(S, K, T, r, q, sigma)          -> per-share call, VND
  - calculate_analytical_greeks(S, K, T, r, q, sigma, exercise_ratio=...) -> WarrantGreeks

Independent references (tests/quant_reference.py, never imported by app/):
  1. ref_call_share            - Simpson quadrature of the risk-neutral expectation
  2. ref_bs_greeks_closed_form - textbook BSM via math.erfc (different CDF routine, layout)
  3. PINNED                    - hand-verifiable literals from (2), cross-checked by (1)
  + finite differences of the *production* pricing function (self-consistency)

UNITS
  S, K            : VND
  T               : years (ACT/365 in the engine; here passed directly)
  r, q, sigma     : annualized decimals (0.05 == 5%)
  call/price/theta/vega/rho : VND
  gamma           : 1 / VND
  delta           : dimensionless (VND change in CW per +1 VND of S)
  vega, rho       : per +0.01 (one percentage point) move
  theta           : per calendar day = instantaneous (-dV/dt) / 365

TOLERANCES  (see each test for the rationale)
"""

import math

import pytest

from app.quant.black_scholes import bs_call_price_share, calculate_analytical_greeks
from tests.quant_reference import (
    PINNED,
    assert_price_converged,
    ref_bs_greeks_closed_form,
    ref_call_share,
    ref_cw_greeks_fd,
)

ALL_VECTORS = list(PINNED.items())


# --------------------------------------------------------------------------- #
# Known-value: production vs pinned literals + live independent references
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name,data", ALL_VECTORS, ids=[n for n, _ in ALL_VECTORS])
def test_known_value_price_and_greeks(name, data):
    """Production BS price + all Greeks vs independently-derived expected values.

    Covers q = 0 (V1, V2, V6, V8) and q > 0 (V3=4%, V4=2%, V5=2%, V7=3%).

    Tolerances:
      call_share : 5e-3 VND  (quadrature oracle rel. error ~1e-8; closed form exact;
                              this margin is ~4 orders above the actual disagreement)
      price      : 1e-2 VND  (production rounds theoretical_price to 2 dp)
      delta      : 1e-4      (production rounds to 5 dp; refs agree to ~5e-6)
      gamma      : 1e-8 + 1e-3*|gamma|   (production rounds to 8 dp; relative 0.1%)
      vega/rho/theta : 2e-2 VND  (production rounds to 2 dp -> +/-5e-3; refs agree ~4e-3)
    """
    S, K, T, r, q, sigma, ratio = data["inputs"]
    assert_price_converged(S, K, T, r, q, sigma)

    prod_call = bs_call_price_share(S, K, T, r, q, sigma)
    g = calculate_analytical_greeks(S, K, T, r, q, sigma, exercise_ratio=ratio)
    cf = ref_bs_greeks_closed_form(S, K, T, r, q, sigma, ratio) if T > 0 else None
    quad_call = ref_call_share(S, K, T, r, q, sigma)

    # price: three independent numbers must agree
    assert prod_call == pytest.approx(data["call_share"], abs=5e-3)
    assert prod_call == pytest.approx(quad_call, abs=max(5e-3, 5e-7 * max(1.0, quad_call)))
    if cf is not None:
        assert prod_call == pytest.approx(cf["call_share"], abs=5e-3)

    assert g.theoretical_price is not None
    assert g.theoretical_price == pytest.approx(data["price"], abs=1e-2)
    assert g.theoretical_price == pytest.approx(prod_call / ratio, abs=1e-2)

    # d1 / d2 pinned for V1 - implicitly validates the CDF arguments
    if "d1" in data and cf is not None:
        assert cf["d1"] == pytest.approx(data["d1"], abs=1e-5)
        assert cf["d2"] == pytest.approx(data["d2"], abs=1e-5)

    for greek in ("delta", "gamma", "vega", "rho", "theta"):
        prod_v = getattr(g, greek)
        assert prod_v is not None, f"{greek} unexpectedly None for {name}"
        exp = data[greek]
        if greek == "delta":
            tol = 1e-4
        elif greek == "gamma":
            tol = 1e-8 + 1e-3 * abs(exp)
        else:
            tol = 2e-2
        assert prod_v == pytest.approx(exp, abs=tol), (
            f"{name}.{greek}: production={prod_v} vs pinned={exp}"
        )
        if cf is not None:
            assert prod_v == pytest.approx(cf[greek], abs=max(tol, 2e-2)), (
                f"{name}.{greek}: production={prod_v} vs closed-form ref={cf[greek]}"
            )


# --------------------------------------------------------------------------- #
# Finite differences of the PRODUCTION pricing function (self-consistency).
# Catches an error in calculate_analytical_greeks' formula assembly even if
# bs_call_price_share is fine (they are separate code).
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name,data", ALL_VECTORS, ids=[n for n, _ in ALL_VECTORS])
def test_finite_difference_vs_production_pricer(name, data):
    """Analytic Greeks vs central differences of bs_call_price_share / ratio.

    Steps and their rationale:
      h_S    = 5e-4 * S      -> central-diff O((h/S)^2) ~ 2.5e-7 on delta;
                               for the second difference (gamma) the O(h^2) truncation
                               is ~1e-3 relative, hence the relative gamma tolerance.
      h_sig  = 1e-4          -> O(h^2)=1e-8 abs on dV/dsigma; * 0.01 -> negligible.
      h_r    = 1e-5          -> same order.
      theta  = instantaneous symmetric derivative -[C(T+dt)-C(T-dt)]/(2 dt)/365,
               dt = 5e-6. This IS the project convention (see docstring). The naive
               1-day drop  C(T-1/365)-C(T)  differs from it by theta's own convexity
               and is only ~equal away from expiry - so it is NOT used here.
    """
    S, K, T, r, q, sigma, ratio = data["inputs"]
    if T <= 0:
        pytest.skip("finite-difference cross-check is for T > 0")

    g = calculate_analytical_greeks(S, K, T, r, q, sigma, exercise_ratio=ratio)

    def cw(s_=S, k_=K, t_=T, r_=r, q_=q, sig_=sigma):
        return bs_call_price_share(s_, k_, t_, r_, q_, sig_) / ratio

    h_s = 5e-4 * S
    c0, cp, cm = cw(), cw(s_=S + h_s), cw(s_=S - h_s)
    fd_delta = (cp - cm) / (2 * h_s)
    fd_gamma = (cp - 2 * c0 + cm) / (h_s * h_s)

    h_sig = 1e-4
    fd_vega = (cw(sig_=sigma + h_sig) - cw(sig_=sigma - h_sig)) / (2 * h_sig) * 0.01

    h_r = 1e-5
    fd_rho = (cw(r_=r + h_r) - cw(r_=r - h_r)) / (2 * h_r) * 0.01

    dt = 5e-6
    fd_theta = -(cw(t_=T + dt) - cw(t_=T - dt)) / (2 * dt) / 365.0

    assert g.delta == pytest.approx(fd_delta, abs=2e-4)
    assert g.gamma == pytest.approx(fd_gamma, abs=1e-8 + 5e-3 * abs(fd_gamma))
    assert g.vega == pytest.approx(fd_vega, abs=2e-2)
    assert g.rho == pytest.approx(fd_rho, abs=2e-2)
    assert g.theta == pytest.approx(fd_theta, abs=2e-2 + 1e-2 * abs(fd_theta))


# --------------------------------------------------------------------------- #
# Targeted anti-regression tests for the specific bug classes the audit named
# --------------------------------------------------------------------------- #
def test_vega_is_per_one_percent_not_per_unit_vol():
    """Vega must be d(price)/d(sigma) * 0.01, NOT d(price)/d(sigma).

    A factor-of-100 error would make vega ~2115 instead of ~21 for V1.
    """
    S, K, T, r, q, sigma, ratio = PINNED["V1_ATM_q0"]["inputs"]
    g = calculate_analytical_greeks(S, K, T, r, q, sigma, exercise_ratio=ratio)

    per_unit = (
        bs_call_price_share(S, K, T, r, q, sigma + 1e-4) / ratio
        - bs_call_price_share(S, K, T, r, q, sigma - 1e-4) / ratio
    ) / (2e-4)
    per_one_pct = per_unit * 0.01

    assert g.vega is not None
    assert g.vega == pytest.approx(per_one_pct, abs=2e-2)
    assert g.vega == pytest.approx(21.15, abs=0.1)          # ~21, not ~2115 and not ~0.21
    assert not (2000 < g.vega < 2200)


def test_theta_is_daily_not_annual():
    """Theta must be the per-calendar-day value (annual / 365), not the annual value.

    For V1 the annual theta is ~ -1435 VND; the daily is ~ -3.93 VND.
    """
    S, K, T, r, q, sigma, ratio = PINNED["V1_ATM_q0"]["inputs"]
    g = calculate_analytical_greeks(S, K, T, r, q, sigma, exercise_ratio=ratio)

    dt = 5e-6
    annual = -(
        bs_call_price_share(S, K, T + dt, r, q, sigma) / ratio
        - bs_call_price_share(S, K, T - dt, r, q, sigma) / ratio
    ) / (2 * dt)

    assert g.theta is not None
    assert g.theta == pytest.approx(annual / 365.0, abs=2e-2)
    assert -6.0 < g.theta < -2.0                            # single digits, i.e. daily
    assert not (-2000 < g.theta < -1000)                    # would be the annual value


def test_dividend_yield_reduces_call_and_delta():
    """q enters the model correctly: a higher dividend yield lowers a call and its delta."""
    S, K, T, r, sigma, ratio = 30000.0, 30000.0, 0.5, 0.05, 0.30, 1.0

    p_q0 = bs_call_price_share(S, K, T, r, 0.0, sigma)
    p_q3 = bs_call_price_share(S, K, T, r, 0.03, sigma)
    p_q6 = bs_call_price_share(S, K, T, r, 0.06, sigma)
    assert p_q0 > p_q3 > p_q6 > 0.0

    d_q0 = calculate_analytical_greeks(S, K, T, r, 0.0, sigma, exercise_ratio=ratio).delta
    d_q6 = calculate_analytical_greeks(S, K, T, r, 0.06, sigma, exercise_ratio=ratio).delta
    assert d_q0 is not None and d_q6 is not None and d_q0 > d_q6

    # magnitude sanity vs the independent closed form
    cf_q3 = ref_bs_greeks_closed_form(S, K, T, r, 0.03, sigma, ratio)
    assert p_q3 == pytest.approx(cf_q3["call_share"], abs=5e-3)


def test_greek_signs_for_vanilla_call():
    """Delta in (0, 1/k); gamma > 0; vega > 0; rho > 0; theta < 0 for a non-expiring OTM/ATM call."""
    S, K, T, r, q, ratio = 24000.0, 25000.0, 0.4, 0.05, 0.0, 4.0
    g = calculate_analytical_greeks(S, K, T, r, q, 0.35, exercise_ratio=ratio)
    assert None not in (g.delta, g.gamma, g.vega, g.rho, g.theta)
    assert g.delta is not None and 0.0 < g.delta < 1.0 / ratio
    assert g.gamma is not None and g.gamma > 0.0
    assert g.vega is not None and g.vega > 0.0
    assert g.rho is not None and g.rho > 0.0
    assert g.theta is not None and g.theta < 0.0


@pytest.mark.parametrize(
    "name,data",
    [(n, d) for n, d in ALL_VECTORS if d["inputs"][2] >= 0.1],   # skip near-expiry (FD-noisy)
    ids=[n for n, d in ALL_VECTORS if d["inputs"][2] >= 0.1],
)
def test_greeks_vs_fully_independent_quadrature_fd(name, data):
    """Third angle: production analytic Greeks vs finite differences of the *quadrature*
    price (ref_cw_greeks_fd). Shares no code with production at all - not even a formula.
    Near-expiry vectors (T < 0.1) are excluded here because the oracle's second-difference
    gamma is FD-noise-limited there; those are covered by the closed-form reference above.
    """
    S, K, T, r, q, sigma, ratio = data["inputs"]
    if T <= 0:
        pytest.skip("T > 0 only")
    g = calculate_analytical_greeks(S, K, T, r, q, sigma, exercise_ratio=ratio)
    fd = ref_cw_greeks_fd(S, K, T, r, q, sigma, ratio)

    assert g.delta == pytest.approx(fd["delta"], abs=5e-4)
    assert g.gamma == pytest.approx(fd["gamma"], abs=1e-8 + 5e-3 * abs(fd["gamma"]))
    assert g.vega == pytest.approx(fd["vega"], abs=3e-2)
    assert g.rho == pytest.approx(fd["rho"], abs=3e-2)
    assert g.theta == pytest.approx(fd["theta"], abs=3e-2 + 1e-2 * abs(fd["theta"]))


def test_no_arbitrage_bounds_hold_on_grid():
    """max(0, S e^-qT - K e^-rT) <= C_share <= S e^-qT  for a spread of parameters."""
    for S in (10000.0, 25000.0, 60000.0):
        for K in (12000.0, 25000.0, 50000.0):
            for T in (0.05, 0.5, 2.0):
                for q in (0.0, 0.03):
                    for sigma in (0.1, 0.4, 1.2):
                        c = bs_call_price_share(S, K, T, 0.05, q, sigma)
                        lo = max(0.0, S * math.exp(-q * T) - K * math.exp(-0.05 * T))
                        hi = S * math.exp(-q * T)
                        assert c >= lo - 1e-6
                        assert c <= hi + 1e-6
