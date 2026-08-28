"""
Historical-volatility primitive verification - production code only.

Production under test (app.quant.historical_volatility):
    calculate_log_returns(prices)            -> [ln(P_t / P_{t-1}) ...], skips non-positive
    calculate_sample_std(values)             -> sample stdev, Bessel (N-1); 0.0 if n < 2
    calculate_historical_volatility(prices, window=22, min_periods=10)
        -> annualized decimal HV over the last (window+1) closes, or None if short
    calculate_multi_window_hv(symbol, date, prices) -> HistoricalVolatilityPoint(hv22/66/132/252)

Canonical window for the theoretical-price path: HV_22 (settings.QUANT_HV_WINDOW_SESSIONS).

Independent reference: hv_annualized_reference() in tests/quant_reference.py uses
statistics.stdev (a different sample-stdev implementation) * sqrt(252).
"""

import math
import statistics

import pytest

from app.core.config import settings
from app.quant.historical_volatility import (
    calculate_historical_volatility,
    calculate_log_returns,
    calculate_multi_window_hv,
    calculate_sample_std,
)
from tests.quant_reference import hv_annualized_reference

ANNUALIZE = math.sqrt(252.0)


def _prices_from_log_returns(returns, p0=100.0):
    """Build a price path whose successive log ratios are exactly `returns`."""
    prices = [p0]
    for r in returns:
        prices.append(prices[-1] * math.exp(r))
    return prices


# --------------------------------------------------------------------------- #
# Building blocks
# --------------------------------------------------------------------------- #
def test_log_returns_match_definition_and_skip_nonpositive():
    prices = [100.0, 101.0, 99.0, 102.5]
    rets = calculate_log_returns(prices)
    assert rets == pytest.approx([math.log(101 / 100), math.log(99 / 101), math.log(102.5 / 99)])

    # a zero / negative price breaks the pair around it
    dirty = [100.0, 0.0, 105.0, -3.0, 110.0]
    assert calculate_log_returns(dirty) == []   # every consecutive pair touches a non-positive value


def test_sample_std_uses_bessel_correction():
    vals = [0.01, -0.01, 0.02, -0.02, 0.0]
    assert calculate_sample_std(vals) == pytest.approx(statistics.stdev(vals), rel=1e-12)
    assert calculate_sample_std([0.5]) == 0.0    # n < 2


# --------------------------------------------------------------------------- #
# Known-value HV_22 against an independent stdev implementation
# --------------------------------------------------------------------------- #
def test_hv22_known_alternating_return_series():
    # 22 returns alternating +/-0.02  ->  23 prices
    returns = [0.02 if i % 2 == 0 else -0.02 for i in range(22)]
    prices = _prices_from_log_returns(returns)
    assert len(prices) == 23

    hv = calculate_historical_volatility(
        prices, window=settings.QUANT_HV_WINDOW_SESSIONS, min_periods=settings.QUANT_HV_MIN_SESSIONS
    )
    # Independent expectation: statistics.stdev(returns) * sqrt(252), rounded to 4 dp.
    expected = round(statistics.stdev(returns) * ANNUALIZE, 4)
    assert hv == expected
    assert hv == round(hv_annualized_reference(returns), 4)
    # Hand check: stdev of 22 values +/-0.02 (mean 0) = sqrt(22*0.0004/21) = 0.020471
    assert hv == pytest.approx(0.020471 * ANNUALIZE, abs=5e-4)


def test_hv22_known_ramp_series():
    # a non-symmetric series so mean != 0
    returns = [0.001 * (i - 8) for i in range(22)]      # -0.008 .. +0.013
    prices = _prices_from_log_returns(returns)
    hv = calculate_historical_volatility(prices, window=22, min_periods=10)
    assert hv == round(statistics.stdev(returns) * ANNUALIZE, 4)


def test_annualization_is_sqrt_252():
    returns = [(-1) ** i * 0.015 for i in range(22)]
    prices = _prices_from_log_returns(returns)
    hv = calculate_historical_volatility(prices, window=22, min_periods=10)
    daily_std = statistics.stdev(returns)
    # hv is round(daily_std * sqrt(252), 4); the ratio recovers sqrt(252) up to that rounding.
    assert hv == round(daily_std * math.sqrt(252.0), 4)
    assert hv / daily_std == pytest.approx(math.sqrt(252.0), rel=1e-3)   # ~15.87, not 12 (252d) nor 16 wrong
    assert math.sqrt(252.0) == pytest.approx(15.8745, abs=1e-3)          # the factor the code uses


# --------------------------------------------------------------------------- #
# Degenerate & boundary inputs
# --------------------------------------------------------------------------- #
def test_constant_price_series_has_zero_volatility():
    assert calculate_historical_volatility([100.0] * 30, window=22, min_periods=10) == 0.0


def test_constant_log_return_series_has_zero_volatility():
    prices = _prices_from_log_returns([0.005] * 25)     # exponential growth, zero variance
    assert calculate_historical_volatility(prices, window=22, min_periods=10) == 0.0


def test_minimum_observations_boundary():
    # need at least (min_periods + 1) prices -> 11 for min_periods=10
    ten_prices = _prices_from_log_returns([0.01, -0.01] * 4 + [0.01])   # 10 prices, 9 returns
    assert calculate_historical_volatility(ten_prices, window=22, min_periods=10) is None

    eleven_prices = _prices_from_log_returns([0.01, -0.01] * 5)          # 11 prices, 10 returns
    hv = calculate_historical_volatility(eleven_prices, window=22, min_periods=10)
    assert hv is not None and hv > 0.0


def test_insufficient_history_returns_none():
    assert calculate_historical_volatility([100.0, 101.0, 102.0], window=22, min_periods=10) is None
    assert calculate_historical_volatility([], window=22, min_periods=10) is None
    assert calculate_historical_volatility([100.0], window=22, min_periods=10) is None


def test_window_slicing_uses_only_the_last_window_plus_one_closes():
    # 30 quiet returns then 22 volatile returns; HV must reflect ONLY the last 22.
    quiet = [0.0005 * (-1) ** i for i in range(30)]
    volatile = [0.04 * (-1) ** i for i in range(22)]
    prices = _prices_from_log_returns(quiet + volatile)      # 53 prices

    hv_full = calculate_historical_volatility(prices, window=22, min_periods=10)
    hv_tail_only = calculate_historical_volatility(prices[-23:], window=22, min_periods=10)
    assert hv_full == hv_tail_only
    # and it is the volatile regime, not the blended one
    assert hv_full == pytest.approx(round(statistics.stdev(volatile) * ANNUALIZE, 4), abs=1e-4)


# --------------------------------------------------------------------------- #
# Canonical window + multi-window utility
# --------------------------------------------------------------------------- #
def test_hv22_is_the_canonical_configured_window():
    assert settings.QUANT_HV_WINDOW_SESSIONS == 22
    assert settings.QUANT_HV_MIN_SESSIONS == 10


def test_multi_window_hv_windows_match_the_primitive():
    returns = [0.02 * math.sin(i * 0.5) + 0.001 for i in range(80)]      # 80 returns
    prices = _prices_from_log_returns(returns)
    point = calculate_multi_window_hv("HPG", "2026-08-27", prices)

    assert point.symbol == "HPG" and point.date == "2026-08-27"
    assert point.hv22 == calculate_historical_volatility(prices, window=22, min_periods=10)
    assert point.hv66 == calculate_historical_volatility(prices, window=66, min_periods=30)
    assert point.hv132 == calculate_historical_volatility(prices, window=132, min_periods=60)
    assert point.hv252 is None                             # 80 returns < 120 min for HV252
    assert point.hv22 is not None and point.hv66 is not None
