"""
Mathematical Black-Scholes Engine & Bounded Implied Volatility Root Solver.
Implements European Call pricing, analytical Greeks, boundary validation, and IV inversion
tailored for Covered Warrants with explicit exercise-ratio scaling.
"""

import math
import logging
from typing import Optional, Tuple
from app.quant.schemas import WarrantGreeks, GreeksVolatilitySource

logger = logging.getLogger(__name__)

# Mathematical Constants
SQRT_2 = math.sqrt(2.0)
INV_SQRT_2PI = 1.0 / math.sqrt(2.0 * math.pi)


def cnd(x: float) -> float:
    """Standard Normal Cumulative Distribution Function N(x) using high-precision error function."""
    return 0.5 * (1.0 + math.erf(x / SQRT_2))


def ndf(x: float) -> float:
    """Standard Normal Probability Density Function N'(x) = phi(x)."""
    return INV_SQRT_2PI * math.exp(-0.5 * x * x)


def bs_call_price_share(
    S: float,
    K: float,
    T: float,
    r: float,
    q: float,
    sigma: float,
) -> float:
    """
    Computes European Call Option price for 1 share of underlying equity.
    """
    if S <= 0 or K <= 0 or sigma <= 0:
        return 0.0
    if T <= 0:
        return max(0.0, S - K)

    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T

    disc_s = math.exp(-q * T)
    disc_k = math.exp(-r * T)

    call_price = S * disc_s * cnd(d1) - K * disc_k * cnd(d2)
    return max(0.0, call_price)


def check_call_price_bounds(
    S: float,
    K: float,
    T: float,
    r: float,
    q: float,
    market_price_share: float,
    tolerance: float = 1e-4,
) -> Tuple[bool, Optional[str]]:
    """
    Validates share-equivalent market price against theoretical European Call no-arbitrage bounds:
    Lower bound: max(0, S * e^(-qT) - K * e^(-rT))
    Upper bound: S * e^(-qT)
    """
    if market_price_share <= 0:
        return False, "INVALID_MARKET_PRICE_LEQ_ZERO"
    if S <= 0 or K <= 0 or T <= 0:
        return False, "INVALID_INPUT_PARAMETERS"

    disc_s = math.exp(-q * T)
    disc_k = math.exp(-r * T)

    lower_bound = max(0.0, S * disc_s - K * disc_k)
    upper_bound = S * disc_s

    if market_price_share < (lower_bound - tolerance):
        return False, f"PRICE_BELOW_LOWER_BOUND (Price={market_price_share:.2f} < Min={lower_bound:.2f})"
    if market_price_share > (upper_bound + tolerance):
        return False, f"PRICE_ABOVE_UPPER_BOUND (Price={market_price_share:.2f} > Max={upper_bound:.2f})"

    return True, None


def solve_implied_volatility(
    S: float,
    K: float,
    T: float,
    r: float,
    q: float,
    market_price_cw: float,
    exercise_ratio: float = 1.0,
    sigma_min: float = 1e-4,
    sigma_max: float = 5.0,
    price_tolerance: float = 1e-4,
    max_iterations: int = 100,
) -> Tuple[Optional[float], Optional[str]]:
    """
    Solves Implied Volatility (sigma) for a Covered Warrant using bounded bisection root solver.

    Invariant:
    market_price_share = market_price_cw * exercise_ratio
    BS_call_price_share(S, K, T, r, q, sigma) == market_price_share
    """
    if market_price_cw <= 0:
        return None, "INVALID_INPUT"
    if exercise_ratio <= 0:
        return None, "INVALID_INPUT"
    if S <= 0 or K <= 0 or T <= 0:
        return None, "INVALID_INPUT"

    # Convert CW market price to Share-Equivalent option price
    market_price_share = market_price_cw * exercise_ratio

    # 1. No-arbitrage boundary check
    valid, _ = check_call_price_bounds(S, K, T, r, q, market_price_share, tolerance=price_tolerance)
    if not valid:
        return None, "PRICE_OUTSIDE_MODEL_BOUNDS"

    # 2. Check bounds on sigma domain [sigma_min, sigma_max]
    price_low = bs_call_price_share(S, K, T, r, q, sigma_min)
    price_high = bs_call_price_share(S, K, T, r, q, sigma_max)

    if market_price_share < price_low:
        if abs(market_price_share - price_low) <= price_tolerance:
            return round(sigma_min, 6), None
        return None, "NO_ROOT_IN_SIGMA_RANGE"

    if market_price_share > price_high:
        if abs(market_price_share - price_high) <= price_tolerance:
            return round(sigma_max, 6), None
        return None, "NO_ROOT_IN_SIGMA_RANGE"

    # 3. Bounded Bisection Root Solver
    low = sigma_min
    high = sigma_max

    for _ in range(max_iterations):
        mid = 0.5 * (low + high)
        price_mid = bs_call_price_share(S, K, T, r, q, mid)
        diff = price_mid - market_price_share

        if abs(diff) <= price_tolerance or (high - low) <= 1e-5:
            return round(mid, 6), None

        if diff > 0:
            high = mid
        else:
            low = mid

    # Return best convergence candidate if close enough
    final_mid = 0.5 * (low + high)
    final_price = bs_call_price_share(S, K, T, r, q, final_mid)
    if abs(final_price - market_price_share) <= (price_tolerance * 5.0):
        return round(final_mid, 6), None

    return None, "CONVERGENCE_FAILED"


def calculate_analytical_greeks(
    S: float,
    K: float,
    T: float,
    r: float,
    q: float,
    sigma: float,
    exercise_ratio: float = 1.0,
    volatility_source: GreeksVolatilitySource = GreeksVolatilitySource.UNAVAILABLE,
    theoretical_price: Optional[float] = None,
    model_price_at_iv_mid: Optional[float] = None,
) -> WarrantGreeks:
    """
    Computes analytical Black-Scholes Greeks and scales them by the Covered Warrant Exercise Ratio.
    Strictly decouples independent theoretical fair price from circular Model Price @ IV Mid.

    Units:
    - delta: Change in CW price (VND) per +1 VND move in underlying equity (Delta_share / exercise_ratio)
    - gamma: Change in CW Delta per +1 VND move in underlying equity (Gamma_share / exercise_ratio)
    - theta: Time decay in CW price (VND) per calendar day (Theta_yearly / (365 * exercise_ratio))
    - vega: CW price change in VND for +1% (0.01) volatility increase (Vega_unit * 0.01 / exercise_ratio)
    - rho: CW price change in VND for +1% (0.01) interest rate increase (Rho_unit * 0.01 / exercise_ratio)
    - theoretical_price: Evaluated with independent theoretical volatility (None if unavailable)
    - model_price_at_iv_mid: Evaluated at IV_MID (reproduces market midpoint)
    """
    if S <= 0 or K <= 0 or exercise_ratio <= 0:
        return WarrantGreeks(volatility_source=GreeksVolatilitySource.UNAVAILABLE)

    if T <= 0:
        intrinsic_cw = round(max(0.0, S - K) / exercise_ratio, 2)
        return WarrantGreeks(
            theoretical_price=theoretical_price if theoretical_price is not None else intrinsic_cw,
            model_price_at_iv_mid=model_price_at_iv_mid if model_price_at_iv_mid is not None else intrinsic_cw,
            delta=round((1.0 / exercise_ratio) if S > K else 0.0, 5),
            gamma=0.0,
            theta=0.0,
            vega=0.0,
            rho=0.0,
            volatility_used=sigma,
            volatility_source=volatility_source,
        )

    clamped_sigma = max(1e-4, min(sigma, 10.0))
    sqrt_T = math.sqrt(T)
    disc_s = math.exp(-q * T)
    disc_k = math.exp(-r * T)

    d1 = (math.log(S / K) + (r - q + 0.5 * clamped_sigma * clamped_sigma) * T) / (clamped_sigma * sqrt_T)
    d2 = d1 - clamped_sigma * sqrt_T

    # 1. Option on 1 underlying share
    bs_call_share = max(0.0, S * disc_s * cnd(d1) - K * disc_k * cnd(d2))

    # 2. Greeks on 1 underlying share
    delta_share = disc_s * cnd(d1)
    gamma_share = (disc_s * ndf(d1)) / (S * clamped_sigma * sqrt_T)
    theta_yearly_share = (
        -(S * disc_s * ndf(d1) * clamped_sigma) / (2.0 * sqrt_T)
        + q * S * disc_s * cnd(d1)
        - r * K * disc_k * cnd(d2)
    )
    vega_unit_share = S * disc_s * sqrt_T * ndf(d1)
    rho_unit_share = K * T * disc_k * cnd(d2)

    # 3. Scale by Exercise Ratio for Covered Warrant
    cw_model_price = round(bs_call_share / exercise_ratio, 2)
    cw_delta = delta_share / exercise_ratio
    cw_gamma = gamma_share / exercise_ratio
    cw_theta_daily = theta_yearly_share / (365.0 * exercise_ratio)
    cw_vega_1pct = (vega_unit_share * 0.01) / exercise_ratio
    cw_rho_1pct = (rho_unit_share * 0.01) / exercise_ratio

    # Resolve theoretical_price vs model_price_at_iv_mid
    resolved_theo_price = theoretical_price
    resolved_model_mid = model_price_at_iv_mid

    if volatility_source == GreeksVolatilitySource.IV_MID:
        if resolved_model_mid is None:
            resolved_model_mid = cw_model_price
    else:
        if resolved_theo_price is None:
            resolved_theo_price = cw_model_price

    return WarrantGreeks(
        theoretical_price=resolved_theo_price,
        model_price_at_iv_mid=resolved_model_mid,
        delta=round(cw_delta, 5),
        gamma=round(cw_gamma, 8),
        theta=round(cw_theta_daily, 2),
        vega=round(cw_vega_1pct, 2),
        rho=round(cw_rho_1pct, 2),
        volatility_used=round(clamped_sigma, 4),
        volatility_source=volatility_source,
    )
