"""
Historical Volatility (HV) Analytics Module.
Calculates annualized standard deviation of log returns from historical close prices:
HV = std(ln(P_t / P_{t-1})) * sqrt(252)
"""

import math
import logging
from typing import List, Optional, Dict
from app.quant.schemas import HistoricalVolatilityPoint

logger = logging.getLogger(__name__)

ANNUALIZATION_FACTOR = math.sqrt(252.0)  # 252 trading sessions per year


def calculate_log_returns(prices: List[float]) -> List[float]:
    """Computes daily logarithmic returns ln(P_t / P_{t-1})."""
    if len(prices) < 2:
        return []
    returns: List[float] = []
    for i in range(1, len(prices)):
        p_prev = prices[i - 1]
        p_curr = prices[i]
        if p_prev > 0 and p_curr > 0:
            returns.append(math.log(p_curr / p_prev))
    return returns


def calculate_sample_std(values: List[float]) -> float:
    """Calculates sample standard deviation with Bessel's correction (N-1)."""
    n = len(values)
    if n < 2:
        return 0.0
    mean_val = sum(values) / n
    variance = sum((x - mean_val) ** 2 for x in values) / (n - 1)
    return math.sqrt(variance)


def calculate_historical_volatility(
    prices: List[float],
    window: int = 22,
    min_periods: int = 10,
) -> Optional[float]:
    """
    Computes annualized Historical Volatility for a given price series window.
    Returns decimal volatility (e.g. 0.325 = 32.5%).
    """
    if len(prices) < (window + 1):
        # If insufficient data, use all available if >= min_periods
        if len(prices) < (min_periods + 1):
            return None
        sub_prices = prices
    else:
        sub_prices = prices[-(window + 1):]

    log_rets = calculate_log_returns(sub_prices)
    if len(log_rets) < min_periods:
        return None

    daily_std = calculate_sample_std(log_rets)
    annualized_hv = daily_std * ANNUALIZATION_FACTOR
    return round(annualized_hv, 4)


def calculate_multi_window_hv(
    symbol: str,
    date_str: str,
    prices: List[float],
) -> HistoricalVolatilityPoint:
    """
    Computes multi-window HV points (22, 66, 132, 252 sessions).
    """
    return HistoricalVolatilityPoint(
        symbol=symbol.upper(),
        date=date_str,
        hv22=calculate_historical_volatility(prices, window=22, min_periods=10),
        hv66=calculate_historical_volatility(prices, window=66, min_periods=30),
        hv132=calculate_historical_volatility(prices, window=132, min_periods=60),
        hv252=calculate_historical_volatility(prices, window=252, min_periods=120),
    )
