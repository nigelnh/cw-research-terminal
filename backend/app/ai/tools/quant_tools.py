"""
Read-Only Quantitative Analytics Tools for Research Copilot.
Uses the EXISTING QuantEngine (Black-Scholes, analytical Greeks, HV).
Does NOT reimplement mathematics in the AI layer.
"""

from typing import Dict, Any, List
from datetime import datetime
import logging

from app.quant.quant_engine import live_quant_engine
from app.instruments.instrument_registry import instrument_registry
from app.market_data.trading_calendar import VN_TZ, latest_completed_trading_session

logger = logging.getLogger(__name__)


def _determine_missing_inputs(reason: str) -> List[str]:
    """Helper to categorize missing inputs for structured reporting."""
    r = (reason or "").upper()
    missing = []
    if "STRIKE" in r:
        missing.append("strike_price")
    if "RATIO" in r:
        missing.append("exercise_ratio")
    if "MATURITY" in r or "EXPIR" in r or "T_LEQ_0" in r:
        missing.append("maturity_date")
    if "SPOT" in r or "UNDERLYING" in r:
        missing.append("underlying_spot_price")
    if "TRADE" in r or "NO_TRADE" in r or "LAST" in r:
        missing.append("last_traded_price")
    if "INCOMPLETE" in r:
        missing.extend(["contract_terms", "verified_reference_metadata"])
    if not missing:
        missing.append(reason)
    return list(dict.fromkeys(missing))


async def get_quant(symbol: str) -> Dict[str, Any]:
    """
    Returns quantitative valuation analytics from QuantEngine.
    If analytics cannot be computed due to missing terms, returns structured missing_inputs without hallucinating.
    """
    if not symbol or not isinstance(symbol, str):
        return {
            "symbol": "",
            "status": "INVALID_ARGUMENT",
            "message": "Symbol must be a non-empty string.",
            "provenance": "PROJECT_QUANT_ENGINE",
        }

    sym_clean = symbol.strip().upper()
    # HOSE covered-warrant symbol convention: 'C' + 7 alphanumerics. This is a structural
    # shape check (matches market_state._determine_instrument_type), not a ticker allow-list.
    is_cw = len(sym_clean) == 8 and sym_clean.startswith("C") and sym_clean[1:].isalnum()

    if not is_cw:
        return {
            "symbol": sym_clean,
            "instrument_type": "STOCK",
            "status": "NOT_APPLICABLE",
            "message": f"{sym_clean} is an underlying equity stock. European Call Black-Scholes analytics apply to Covered Warrants.",
            "historical_volatility": None,
            "provenance": "PROJECT_QUANT_ENGINE",
        }

    # Covered Warrant: delegate to canonical LiveQuantEngine
    try:
        analytics = await live_quant_engine.compute_warrant_analytics(sym_clean)
    except Exception as e:
        logger.error(f"Error computing warrant analytics for {sym_clean}: {e}")
        return {
            "symbol": sym_clean,
            "instrument_type": "CW",
            "status": "ERROR",
            "is_available": False,
            "unavailable_reason": str(e),
            "missing_inputs": ["computation_error"],
            "provenance": "PROJECT_QUANT_ENGINE",
        }

    basis = "LIVE"
    as_of_session: str | None = None

    # The live path only produces analytics for the current live session - outside trading
    # hours it returns MARKET_INPUT_SESSION_MISMATCH because the last observed book belongs
    # to a prior session. Fall back to temporally-aligned EOD analytics for the last
    # completed session: the SAME source the watchlist IV columns and the instrument
    # panel's OPTIONS ANALYTICS already display (market_snapshot_resolver._attach_analytics
    # does exactly this live->EOD hop). Without it the AI reports "IV unavailable" while
    # the numbers sit on screen next to it.
    if not analytics.is_available:
        last_session = latest_completed_trading_session(datetime.now(VN_TZ))
        try:
            eod = await live_quant_engine.compute_eod_analytics(sym_clean, last_session)
        except Exception as e:  # noqa: BLE001 - EOD is best-effort; keep the live result
            logger.info("get_quant EOD fallback for %s failed: %s", sym_clean, e)
            eod = None
        if eod is not None:
            # On a closed market the EOD read is authoritative whether or not it solved -
            # its unavailable_reason (e.g. METADATA_NOT_VERIFIED_CURRENT) is more actionable
            # than the live path's session-mismatch.
            analytics = eod
            if eod.is_available:
                basis = "LAST_COMPLETED_SESSION"
                as_of_session = last_session.isoformat()

    if not analytics.is_available:
        missing_inputs = _determine_missing_inputs(analytics.unavailable_reason or "INCOMPLETE_INPUTS")
        return {
            "symbol": sym_clean,
            "instrument_type": "CW",
            "underlying_symbol": analytics.underlying_symbol,
            "status": "INCOMPLETE_INPUTS",
            "is_available": False,
            "unavailable_reason": analytics.unavailable_reason,
            "missing_inputs": missing_inputs,
            "diagnostics": f"Valuation model cannot solve: {analytics.unavailable_reason}. Required valuation inputs are missing or unverified.",
            "volatility_source": "UNAVAILABLE",
            "provenance": "PROJECT_QUANT_ENGINE",
        }

    g = analytics.greeks
    return {
        "symbol": sym_clean,
        "instrument_type": "CW",
        "underlying_symbol": analytics.underlying_symbol,
        "status": "AVAILABLE",
        "is_available": True,
        "basis": basis,
        "as_of_session": as_of_session,
        "iv_bid": analytics.iv_bid,
        "iv_trade": analytics.iv_trade,
        "iv_mid": analytics.iv_mid,
        "iv_ask": analytics.iv_ask,
        "delta": g.delta if g else None,
        "gamma": g.gamma if g else None,
        "theta": g.theta if g else None,
        "vega": g.vega if g else None,
        "rho": g.rho if g else None,
        "moneyness": analytics.moneyness,
        "moneyness_category": analytics.moneyness_category.value if analytics.moneyness_category else None,
        "historical_volatility": analytics.historical_volatility,
        "theoretical_price": analytics.theoretical_price,
        "theoretical_volatility": analytics.theoretical_volatility,
        "theoretical_volatility_source": analytics.theoretical_volatility_source or "UNAVAILABLE",
        "model_price_at_iv_mid": analytics.model_price_at_iv_mid,
        "greeks_volatility_source": g.volatility_source.value if g and g.volatility_source else "UNAVAILABLE",
        "volatility_source": g.volatility_source.value if g and g.volatility_source else "UNAVAILABLE",
        "calculated_at": analytics.calculated_at,
        "provenance": "PROJECT_QUANT_ENGINE",
    }
