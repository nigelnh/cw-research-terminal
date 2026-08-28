"""
Tool Registry and Schema Definitions for Research Copilot.
Declares standard OpenAI/OpenRouter compatible function calling schemas.
Strictly read-only; bounds execution to whitelisted functions.
"""

from typing import Dict, Any, List, Optional
import logging
import inspect

from app.ai.tools.market_tools import (
    get_market_status,
    get_quote,
    get_order_book,
    get_dashboard_snapshot,
)
from app.ai.tools.instrument_tools import get_instrument
from app.ai.tools.quant_tools import get_quant

logger = logging.getLogger(__name__)

TOOL_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_market_status",
            "description": "Returns current market trading session status, active state, upstream feed connection, and Redis cache availability.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_quote",
            "description": "Returns real-time canonical market quote for a stock or Covered Warrant (last price, reference, bid1, ask1, spread, change %, volume).",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "Ticker symbol (e.g. HPG, NVL, VHM, CVHM2615, CHPG2541)",
                    },
                },
                "required": ["symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_order_book",
            "description": "Returns top-3 order book depth (bid1..3 and ask1..3 prices and quantities) for an instrument from MarketState.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "Ticker symbol",
                    },
                },
                "required": ["symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_dashboard_snapshot",
            "description": "Returns live market snapshots for all monitored primary instruments (HPG, NVL, VHM, CVHM2615, CHPG2541) for cross-instrument comparison.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbols": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of symbols to inspect. If omitted, returns all primary monitored symbols.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_instrument",
            "description": "Returns corporate reference contract metadata (issuer, underlying symbol, strike price, exercise ratio, maturity date) from InstrumentRegistry.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "Covered Warrant or equity ticker symbol",
                    },
                },
                "required": ["symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_quant",
            "description": "Returns quantitative valuation analytics (IV Bid/Trade/Ask, Delta, Gamma, Theta, Vega, Moneyness, Historical Volatility, Theoretical Price) from QuantEngine.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "Covered Warrant ticker symbol (e.g. CHPG2541, CVHM2615)",
                    },
                },
                "required": ["symbol"],
            },
        },
    },
]

# Strict Whitelist of callable tool handlers
TOOL_HANDLERS = {
    "get_market_status": get_market_status,
    "get_quote": get_quote,
    "get_order_book": get_order_book,
    "get_dashboard_snapshot": get_dashboard_snapshot,
    "get_instrument": get_instrument,
    "get_quant": get_quant,
}


async def execute_tool(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Safely executes a registered read-only tool with argument validation and error boundaries.
    """
    handler = TOOL_HANDLERS.get(name)
    if not handler:
        return {
            "error": f"Unknown tool '{name}'.",
            "status": "NOT_FOUND",
            "provenance": "TOOL_REGISTRY",
        }

    try:
        # Check if handler is an async coroutine function
        if inspect.iscoroutinefunction(handler):
            if name in ("get_instrument", "get_quant", "get_quote", "get_order_book"):
                symbol = str(args.get("symbol", "")).strip().upper()
                return await handler(symbol=symbol)
            return await handler(**args)
        else:
            if name in ("get_quote", "get_order_book"):
                symbol = str(args.get("symbol", "")).strip().upper()
                return handler(symbol=symbol)
            elif name == "get_dashboard_snapshot":
                syms = args.get("symbols")
                return handler(watched_symbols=syms)
            elif name == "get_market_status":
                return handler()
            return handler(**args)
    except Exception as e:
        logger.error(f"Error executing tool {name} with args {args}: {e}")
        return {
            "error": str(e),
            "status": "EXECUTION_ERROR",
            "tool": name,
            "provenance": "TOOL_REGISTRY",
        }
