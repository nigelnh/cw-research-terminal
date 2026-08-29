"""Back-compat shim.

The canonical trading calendar now lives in :mod:`app.market_data.trading_calendar`
(Step 13C). This module re-exports the names the ingestion layer has always imported so
existing call sites keep working. Do not add logic here - extend the canonical module.
"""

from __future__ import annotations

from app.market_data.trading_calendar import (  # noqa: F401
    TIMEFRAME_MINUTES,
    _TET_WINDOWS,
    expected_trading_days,
    in_tet_window,
    intraday_bar_is_complete,
    is_expected_trading_day,
    is_fixed_holiday,
    is_weekend,
    iter_days,
    last_completed_session_date,
)

__all__ = [
    "TIMEFRAME_MINUTES",
    "expected_trading_days",
    "in_tet_window",
    "intraday_bar_is_complete",
    "is_expected_trading_day",
    "is_fixed_holiday",
    "is_weekend",
    "iter_days",
    "last_completed_session_date",
]
