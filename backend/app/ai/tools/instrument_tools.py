"""
Read-Only Instrument Metadata Tools for Research Copilot.
Uses InstrumentRegistry as the authoritative source for Covered Warrant contract terms.
"""

from typing import Dict, Any
import logging

from app.instruments.instrument_registry import instrument_registry

logger = logging.getLogger(__name__)


async def get_instrument(symbol: str) -> Dict[str, Any]:
    """
    Returns canonical instrument specification and corporate contract terms from InstrumentRegistry.
    Preserves nulls for unverified/missing terms without fabricating generic defaults.
    """
    if not symbol or not isinstance(symbol, str):
        return {
            "symbol": "",
            "status": "INVALID_ARGUMENT",
            "message": "Symbol must be a non-empty string.",
            "provenance": "APP_VALIDATION",
        }

    sym_clean = symbol.strip().upper()
    spec = await instrument_registry.get_instrument(sym_clean)

    if spec:
        eff_strike = spec.effective_strike
        eff_ratio = spec.effective_ratio

        return {
            "symbol": spec.symbol,
            "instrument_type": "CW" if (spec.symbol.startswith("C") and len(spec.symbol) >= 6) else "STOCK",
            "issuer": spec.issuer if spec.issuer != "UNKNOWN" else None,
            "underlying_symbol": spec.underlying_symbol if spec.underlying_symbol != "UNKNOWN" else None,
            "strike_price": eff_strike,
            "exercise_ratio": eff_ratio,
            "maturity_date": spec.maturity_date,
            "last_trading_date": spec.last_trading_date,
            "is_adjusted": spec.is_adjusted,
            "lifecycle_status": spec.status.value if hasattr(spec.status, "value") else str(spec.status),
            "metadata_quality": spec.data_quality.value if hasattr(spec.data_quality, "value") else str(spec.data_quality),
            "metadata_verification": spec.metadata_verification.value if hasattr(spec.metadata_verification, "value") else str(spec.metadata_verification),
            "provenance": spec.metadata_source or "INSTRUMENT_REGISTRY",
        }

    # If symbol is an underlying stock (e.g. HPG, NVL, VHM)
    is_cw = sym_clean.startswith("C") and len(sym_clean) >= 6
    if not is_cw:
        return {
            "symbol": sym_clean,
            "instrument_type": "STOCK",
            "issuer": None,
            "underlying_symbol": None,
            "strike_price": None,
            "exercise_ratio": None,
            "maturity_date": None,
            "last_trading_date": None,
            "is_adjusted": False,
            "lifecycle_status": "ACTIVE",
            "metadata_quality": "STOCK_EQUITY",
            "provenance": "INSTRUMENT_REGISTRY",
        }

    return {
        "symbol": sym_clean,
        "instrument_type": "CW",
        "status": "NOT_FOUND",
        "message": f"Instrument {sym_clean} not found in InstrumentRegistry.",
        "provenance": "INSTRUMENT_REGISTRY",
    }
