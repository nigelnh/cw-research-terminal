"""
Read-Only Quantitative Analytics Tools for Research Copilot.
Uses the EXISTING QuantEngine (Black-Scholes, analytical Greeks, HV).
Does NOT reimplement mathematics in the AI layer.
"""

from typing import Dict, Any, List
import logging

from app.quant.quant_engine import live_quant_engine
from app.instruments.instrument_registry import instrument_registry

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
