"""
Independent oracles for verifying the production Black-Scholes code.

NOT a second production implementation. `app/` never imports this module; it is
test-only, single-purpose, and unoptimised. It provides two *independent* ways to
obtain expected values, each sharing no code, no CDF routine and no formula layout
with `app.quant.black_scholes`:

1. ``ref_call_share`` - a numerical oracle.
   Prices the European call by high-resolution composite Simpson quadrature of the
   risk-neutral expectation
       C_share = e^{-rT} E_Q[ max(S_T - K, 0) ],
       S_T = S exp( (r - q - sigma^2/2) T + sigma sqrt(T) Z ),  Z ~ N(0,1).
   Method is completely different from the closed form. Convergence self-checked
   (relative error vs the analytic form ~1e-8).

2. ``ref_bs_greeks_closed_form`` - an independent analytic reference.
   Textbook Black-Scholes-Merton Greeks written with an explicit dividend term, a
   deliberately different variable layout, and the standard normal CDF built from
   ``math.erfc`` (a different stdlib routine than production's ``math.erf``).

Between (1), (2) and finite differences of the *production* pricing function
(in the tests), a factor-100 Vega error, an annual/daily Theta error, a sign
error, a wrong dividend treatment, or a conversion-ratio scaling error cannot
survive.

Units everywhere: S, K in VND; T in years; r, q, sigma annualized decimals.
Vega / Rho are expressed per +0.01 move. Theta is the instantaneous -dV/dt per
calendar day (annual value / 365) - the same convention as the production code.
"""

from __future__ import annotations

import math

import numpy as np

# --------------------------------------------------------------------------- #
# (1) Numerical oracle: Simpson quadrature of the risk-neutral expectation
# --------------------------------------------------------------------------- #
_N_NODES = 120001         # odd -> composite Simpson
_Z_LIMIT = 16.0           # +/- 16 sd captures the lognormal tail to well below 1e-40

# Finite-difference steps for oracle Greeks. Chosen so central-difference truncation
# O(h^2) stays well under production rounding for non-near-expiry vectors. Near expiry
# (T ~ 1 day) the second-difference gamma / delta from *this* oracle carry larger error;
# tests use the closed-form reference (2) and production self-FD for those.
_H_S_REL = 2e-3
_H_SIGMA = 1e-4
_H_RATE = 1e-5
_H_TIME = 2e-6


def ref_call_share(S: float, K: float, T: float, r: float, q: float, sigma: float) -> float:
    """European call value for ONE underlying share (VND), by Simpson quadrature."""
    if T <= 0.0:
        return max(0.0, S - K)
    if S <= 0.0 or K <= 0.0 or sigma <= 0.0:
        return 0.0

    z = np.linspace(-_Z_LIMIT, _Z_LIMIT, _N_NODES)
    s_t = S * np.exp((r - q - 0.5 * sigma * sigma) * T + sigma * math.sqrt(T) * z)
    integrand = np.maximum(s_t - K, 0.0) * np.exp(-0.5 * z * z)

    h = (2.0 * _Z_LIMIT) / (_N_NODES - 1)
    weights = np.ones(_N_NODES)
    weights[1:-1:2] = 4.0
    weights[2:-1:2] = 2.0
    integral = (h / 3.0) * float(np.sum(weights * integrand))
    return math.exp(-r * T) * integral / math.sqrt(2.0 * math.pi)


def ref_cw_price(S, K, T, r, q, sigma, ratio: float) -> float:
    """Covered-warrant quoted value = per-share call / conversion ratio (applied ONCE)."""
    return ref_call_share(S, K, T, r, q, sigma) / ratio


def ref_cw_greeks_fd(S, K, T, r, q, sigma, ratio: float) -> dict:
    """CW Greeks by central finite differences of the quadrature price (fully independent)."""
    h_s = S * _H_S_REL
    c = ref_cw_price(S, K, T, r, q, sigma, ratio)
    c_sp = ref_cw_price(S + h_s, K, T, r, q, sigma, ratio)
    c_sm = ref_cw_price(S - h_s, K, T, r, q, sigma, ratio)
    vega = (
        ref_cw_price(S, K, T, r, q, sigma + _H_SIGMA, ratio)
        - ref_cw_price(S, K, T, r, q, sigma - _H_SIGMA, ratio)
    ) / (2.0 * _H_SIGMA) * 0.01
    rho = (
        ref_cw_price(S, K, T, r + _H_RATE, q, sigma, ratio)
        - ref_cw_price(S, K, T, r - _H_RATE, q, sigma, ratio)
    ) / (2.0 * _H_RATE) * 0.01
    dvdt = (
        ref_cw_price(S, K, T + _H_TIME, r, q, sigma, ratio)
        - ref_cw_price(S, K, T - _H_TIME, r, q, sigma, ratio)
    ) / (2.0 * _H_TIME)
    return {
        "price": c,
        "delta": (c_sp - c_sm) / (2.0 * h_s),
        "gamma": (c_sp - 2.0 * c + c_sm) / (h_s * h_s),
        "vega": vega,
        "rho": rho,
        "theta": -dvdt / 365.0,
    }


def assert_price_converged(S, K, T, r, q, sigma, rel_tol: float = 1e-6) -> None:
    """Self-check: doubling the quadrature node count must not move the price by `rel_tol`."""
    global _N_NODES
    coarse = ref_call_share(S, K, T, r, q, sigma)
    saved = _N_NODES
    try:
        _N_NODES = 2 * (_N_NODES - 1) + 1
        fine = ref_call_share(S, K, T, r, q, sigma)
    finally:
        _N_NODES = saved
    denom = max(1.0, abs(fine))
    assert abs(coarse - fine) / denom < rel_tol, (
        f"oracle not converged: coarse={coarse}, fine={fine}"
    )


# --------------------------------------------------------------------------- #
# (2) Independent analytic reference: textbook BSM via math.erfc
# --------------------------------------------------------------------------- #
def _norm_cdf_erfc(x: float) -> float:
    """Standard normal CDF via erfc (different stdlib routine than production's erf)."""
    return 0.5 * math.erfc(-x / math.sqrt(2.0))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def ref_bs_greeks_closed_form(S, K, T, r, q, sigma, ratio: float) -> dict:
    """Textbook Black-Scholes-Merton call Greeks, per warrant (divided by `ratio` once).

    Deliberately organised differently from the production code. Dividend yield `q`
    enters the drift and the S-discount factor explicitly.
    """
    if T <= 0.0 or S <= 0.0 or K <= 0.0 or sigma <= 0.0:
        raise ValueError("closed-form reference requires T,S,K,sigma > 0")

    sqrt_t = math.sqrt(T)
    vol_t = sigma * sqrt_t
    disc_r = math.exp(-r * T)
    disc_q = math.exp(-q * T)

    d1 = (math.log(S / K) + (r - q) * T) / vol_t + 0.5 * vol_t
    d2 = d1 - vol_t
    nd1 = _norm_cdf_erfc(d1)
    nd2 = _norm_cdf_erfc(d2)
    pdf1 = _norm_pdf(d1)

    call_share = S * disc_q * nd1 - K * disc_r * nd2

    delta_share = disc_q * nd1
    gamma_share = disc_q * pdf1 / (S * vol_t)
    vega_share_per_unit = S * disc_q * sqrt_t * pdf1          # dC/dsigma  (per 1.00 vol)
    rho_share_per_unit = K * T * disc_r * nd2                 # dC/dr      (per 1.00 rate)
    theta_annual_share = (
        -(S * disc_q * pdf1 * sigma) / (2.0 * sqrt_t)
        + q * S * disc_q * nd1
        - r * K * disc_r * nd2
    )

    return {
        "d1": d1,
        "d2": d2,
        "call_share": call_share,
        "price": call_share / ratio,
        "delta": delta_share / ratio,
        "gamma": gamma_share / ratio,
        "vega": (vega_share_per_unit * 0.01) / ratio,        # per +0.01 vol
        "rho": (rho_share_per_unit * 0.01) / ratio,          # per +0.01 rate
        "theta": theta_annual_share / (365.0 * ratio),       # per calendar day
    }


# --------------------------------------------------------------------------- #
# Hand-verifiable pinned reference values.
#
# Each was produced by the analytic reference (2), cross-checked against the
# quadrature oracle (1) (convergence-checked, ~1e-8 vs the closed form), and can be
# spot-checked against any public Black-Scholes-Merton calculator.
#
# inputs = (S, K, T, r, q, sigma, ratio)
# Units: prices/vega/rho/theta in VND;  gamma in 1/VND;  delta dimensionless.
#        vega, rho per +0.01 move;  theta per calendar day (instantaneous / 365).
# --------------------------------------------------------------------------- #
PINNED: dict = {
    "V1_ATM_q0": {
        "inputs": (22100.0, 22000.0, 0.23886, 0.05, 0.00, 0.2591, 2.0),
        "d1": 0.193443, "d2": 0.066812,
        "call_share": 1296.5278, "price": 648.2639,
        "delta": 0.288347, "gamma": 6.99557e-05,
        "vega": 21.1455, "rho": 13.6728, "theta": -3.9262,
    },
    "V2_ATM_q0_k1": {
        "inputs": (30000.0, 30000.0, 0.25, 0.05, 0.00, 0.30, 1.0),
        "call_share": 1974.9253, "price": 1974.9253,
        "delta": 0.562903, "gamma": 8.75495e-05,
        "vega": 59.0959, "rho": 37.2804, "theta": -11.7572,
    },
    "V3_ATM_q4pct_k1": {
        "inputs": (30000.0, 30000.0, 0.25, 0.05, 0.04, 0.30, 1.0),
        "call_share": 1810.8219, "price": 1810.8219,
        "delta": 0.531180, "gamma": 8.74037e-05,
        "vega": 58.9975, "rho": 35.3115, "theta": -9.8868,
    },
    "V4_deepITM_q2pct_k2": {
        "inputs": (50000.0, 20000.0, 0.50, 0.05, 0.02, 0.25, 2.0),
        "call_share": 29996.2935, "price": 14998.1468,
        "delta": 0.495025, "gamma": 0.0,
        "vega": 0.0, "rho": 48.7655, "theta": 0.0202,
    },
    "V5_deepOTM_q2pct_k1": {
        "inputs": (15000.0, 40000.0, 0.20, 0.05, 0.02, 0.30, 1.0),
        "call_share": 0.0, "price": 0.0,
        "delta": 0.0, "gamma": 0.0, "vega": 0.0, "rho": 0.0, "theta": 0.0,
    },
    "V6_1day_ITM_q0_k1": {
        "inputs": (30500.0, 30000.0, 1.0 / 365.0, 0.05, 0.00, 0.30, 1.0),
        "call_share": 539.2679, "price": 539.2679,
        "delta": 0.857514, "gamma": 0.0004703145,
        "vega": 3.5960, "rho": 0.7018, "theta": -57.4485,
    },
    "V7_longT_hivol_q3pct_k4": {
        "inputs": (30000.0, 30000.0, 3.0, 0.05, 0.03, 0.60, 4.0),
        "call_share": 11373.5532, "price": 2843.3883,
        "delta": 0.164085, "gamma": 2.4748e-06,
        "vega": 40.0925, "rho": 62.3745, "theta": -0.9786,
    },
    "V8_shortT_OTM_hivol_q0_k3": {
        "inputs": (28000.0, 30000.0, 0.02, 0.05, 0.00, 0.80, 3.0),
        "call_share": 551.4516, "price": 183.8172,
        "delta": 0.097693, "gamma": 3.61966e-05,
        "vega": 4.5405, "rho": 0.5103, "theta": -25.2290,
    },
}


def hv_annualized_reference(daily_log_returns) -> float:
    """Independent HV: statistics.stdev (Bessel N-1) * sqrt(252) - a different
    implementation than the production ``calculate_sample_std``."""
    import statistics

    if len(daily_log_returns) < 2:
        return 0.0
    return statistics.stdev(daily_log_returns) * math.sqrt(252.0)
