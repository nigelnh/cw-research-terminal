"""Read-only historical price tool for the Research Assistant.

Bounded by construction:
  * daily timeframe only (the only timeframe persisted PostgreSQL-first),
  * symbol validated against the canonical InstrumentResolver (unknown -> rejected),
  * calendar span clamped to AI_HISTORY_MAX_LOOKBACK_DAYS,
  * at most AI_HISTORY_MAX_POINTS rows returned (older rows are evenly downsampled),
  * NEVER triggers a provider call or gap-fill - it reads only what the store already holds
    (``history_read_service.get_history_readonly``).

Output is compact: a short summary (first/last close, % change, window high/low, count,
coverage note) plus the (possibly downsampled) series. Everything is tagged
``provenance = "HISTORICAL"`` so the model presents it as persisted end-of-day data, not a
live quote.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Dict

from app.core.config import settings
from app.market_data.history_read_service import HistoryRequestError, history_read_service
from app.me.instrument_resolver import InstrumentResolver

logger = logging.getLogger(__name__)

_MAX_LOOKBACK_DAYS = int(getattr(settings, "AI_HISTORY_MAX_LOOKBACK_DAYS", 120))
_MAX_POINTS = int(getattr(settings, "AI_HISTORY_MAX_POINTS", 60))
_MIN_LOOKBACK_DAYS = 5


def _downsample(bars: list, max_points: int) -> list:
    if len(bars) <= max_points:
        return bars
    step = len(bars) / max_points
    picked = [bars[int(i * step)] for i in range(max_points)]
    if picked[-1] is not bars[-1]:
        picked[-1] = bars[-1]  # always keep the most recent session
    return picked


async def get_history(
    symbol: str,
    timeframe: str = "1D",
    lookback_days: int | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
) -> Dict[str, Any]:
    """Return bounded persisted daily OHLCV history for a validated symbol."""
    sym = (symbol or "").strip().upper()
    if not sym:
        return {"symbol": "", "status": "INVALID_ARGUMENT", "message": "Symbol is required.",
                "provenance": "HISTORICAL"}

    tf = (timeframe or "1D").strip().lower().replace("day", "d").replace("daily", "1d")
    if tf in ("d", "1day"):
        tf = "1d"
    if tf != "1d":
        return {
            "symbol": sym, "status": "UNSUPPORTED_TIMEFRAME",
            "message": "Only daily (1D) history is available to the assistant.",
            "provenance": "HISTORICAL",
        }

    resolver = InstrumentResolver()
    resolved = await resolver.resolve(sym)
    if resolved is None:
        return {
            "symbol": sym, "status": "UNKNOWN_SYMBOL",
            "message": f"{sym} is not a recognised instrument in this project.",
            "provenance": "HISTORICAL",
        }

    # Resolve the window: explicit dates win, else lookback_days (clamped), else default.
    if not from_date and not to_date:
        days = lookback_days if lookback_days is not None else 90
        days = max(_MIN_LOOKBACK_DAYS, min(_MAX_LOOKBACK_DAYS, int(days)))
        to_d = date.today()
        from_d = to_d - timedelta(days=days)
        from_date, to_date = from_d.isoformat(), to_d.isoformat()
    else:
        # Clamp an over-wide explicit span rather than rejecting it.
        try:
            _f = date.fromisoformat((from_date or "")[:10]) if from_date else None
            _t = date.fromisoformat((to_date or "")[:10]) if to_date else date.today()
        except ValueError:
            return {"symbol": sym, "status": "INVALID_ARGUMENT",
                    "message": "Dates must be YYYY-MM-DD.", "provenance": "HISTORICAL"}
        if _f is None:
            _f = _t - timedelta(days=90)
        if (_t - _f).days > _MAX_LOOKBACK_DAYS:
            _f = _t - timedelta(days=_MAX_LOOKBACK_DAYS)
        from_date, to_date = _f.isoformat(), _t.isoformat()

    try:
        bars, source = await history_read_service.get_history_readonly(
            sym, timeframe="1d", from_date=from_date, to_date=to_date,
            adjusted=(resolved.instrument_type != "CW"),
        )
    except HistoryRequestError as e:
        return {"symbol": sym, "status": "INVALID_ARGUMENT", "message": str(e),
                "provenance": "HISTORICAL"}
    except Exception as e:  # noqa: BLE001
        logger.warning("get_history(%s) failed: %s", sym, e)
        return {"symbol": sym, "status": "ERROR", "message": "Historical data lookup failed.",
                "provenance": "HISTORICAL"}

    if source == "UNAVAILABLE" or not bars:
        return {
            "symbol": sym, "instrument_type": resolved.instrument_type,
            "status": "NO_DATA",
            "message": (
                "No persisted end-of-day history is available for this symbol in the "
                "requested window. The assistant reads only stored data and does not "
                "fetch new history on demand."
            ),
            "window": {"from": from_date, "to": to_date},
            "provenance": "HISTORICAL",
        }

    full_count = len(bars)
    series = _downsample(bars, _MAX_POINTS)
    closes = [b.close for b in bars if b.close is not None]
    first_close = closes[0] if closes else None
    last_close = closes[-1] if closes else None
    pct = None
    if first_close and last_close and first_close != 0:
        pct = round((last_close - first_close) / first_close * 100.0, 2)

    return {
        "symbol": sym,
        "instrument_type": resolved.instrument_type,
        "timeframe": "1D",
        "price_basis": "RAW" if resolved.instrument_type == "CW" else "ADJUSTED",
        "status": "AVAILABLE",
        "window": {"from": bars[0].date, "to": bars[-1].date},
        "summary": {
            "sessions": full_count,
            "first_close": first_close,
            "last_close": last_close,
            "change_percent": pct,
            "window_high": max((b.high for b in bars if b.high is not None), default=None),
            "window_low": min((b.low for b in bars if b.low is not None), default=None),
            "downsampled_to": len(series) if len(series) != full_count else None,
        },
        "series": [
            {"d": b.date, "o": b.open, "h": b.high, "l": b.low, "c": b.close, "v": b.volume}
            for b in series
        ],
        "provenance": "HISTORICAL",
        "note": (
            "Persisted end-of-day bars only. Not a live quote. CW series are unadjusted "
            "(warrants are dividend-protected); equity series are corporate-action adjusted."
        ),
    }
