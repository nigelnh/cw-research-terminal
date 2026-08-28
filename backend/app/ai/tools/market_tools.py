"""
Read-Only Market Data Tools for Research Copilot.
Consumes the SAME canonical application services (MarketState, MarketSession, Redis warm-cache)
that power the UI WebSocket gateway.
"""

from typing import Dict, Any, Optional, List
import logging

from app.market_data.market_state import market_state
from app.market_data.market_session import market_session
from app.market_data.market_subscription_manager import subscription_manager

logger = logging.getLogger(__name__)

# Primary canonical universe monitored by the platform
DEFAULT_PRIMARY_UNIVERSE = ["HPG", "NVL", "VHM", "CVHM2615", "CHPG2541"]


def get_market_status() -> Dict[str, Any]:
    """
    Exposes canonical market session and gateway status to the Copilot.
    Strictly read-only; never exposes credentials or private auth tokens.
    """
    sess_status = market_session.get_session_status().value
    sess_active = market_session.is_trading_active()
    quote_eligible = sess_active
    vn_now = market_session.get_vn_now()

    health = subscription_manager.provider.get_health()
    feed_connected = bool(
        health.get("trade_stream_connected")
        or health.get("bid_ask_stream_connected")
        or health.get("authenticated")
    )
    upstream_status = health.get("status", "READY" if feed_connected else "DISCONNECTED")

    return {
        "market_session": sess_status,
        "market_session_active": sess_active,
        "quote_display_eligible": quote_eligible,
        "gateway_connected": True,
        "authenticated": bool(health.get("authenticated", True)),
        "upstream_status": upstream_status,
        "cache_available": bool(subscription_manager.store.is_available()),
        "server_time_vn": vn_now.strftime("%Y-%m-%d %H:%M:%S (VN UTC+7)"),
        "provenance": "APP_MARKET_SESSION",
    }


def get_quote(symbol: str) -> Dict[str, Any]:
    """
    Returns canonical market data for a symbol from MarketState.
    Preserves raw VND units for stocks/CWs and decimal percentages.
    """
    if not symbol or not isinstance(symbol, str):
        return {
            "symbol": "",
            "status": "INVALID_ARGUMENT",
            "message": "Symbol must be a non-empty string.",
            "provenance": "APP_VALIDATION",
        }

    sym_clean = symbol.strip().upper()
    quote = market_state.get_quote(sym_clean)
    sess_status = market_session.get_session_status().value
    quote_eligible = market_session.is_display_eligible(quote.received_timestamp if quote else None)

    if not quote:
        return {
            "symbol": sym_clean,
            "status": "UNAVAILABLE",
            "message": f"No live price quote is currently available in MarketState for {sym_clean}.",
            "market_session": sess_status,
            "quote_display_eligible": quote_eligible,
            "data_source": "NONE",
            "provenance": "MARKET_STATE",
        }

    # Calculate spread and spread percentage if bid/ask available
    spread: Optional[float] = None
    spread_pct: Optional[float] = None
    if quote.bid1_price is not None and quote.ask1_price is not None:
        diff = quote.ask1_price - quote.bid1_price
        if diff >= 0:
            spread = diff
            if quote.bid1_price > 0:
                spread_pct = diff / quote.bid1_price

    # Determine instrument type
    inst_type = "CW" if (sym_clean.startswith("C") and len(sym_clean) >= 6) else ("INDEX" if sym_clean.startswith("VN") else "STOCK")
    data_source = "REDIS_WARM_CACHE" if getattr(quote, "is_restored_from_cache", False) else "FIINQUANT_REALTIME"
    cache_state = "REDIS_RESTORED" if getattr(quote, "is_restored_from_cache", False) else "LIVE"

    return {
        "symbol": sym_clean,
        "instrument_type": inst_type,
        "last_price": quote.last_price,
        "reference_price": quote.reference_price,
        "change": quote.price_change,
        "change_percent": quote.price_change_percent,
        "open_price": quote.open_price,
        "high_price": quote.high_price,
        "low_price": quote.low_price,
        "average_price": quote.average_price,
        "total_volume": quote.total_volume,
        "trading_value": quote.trading_value,
        "bid1_price": quote.bid1_price,
        "bid1_quantity": quote.bid1_quantity,
        "ask1_price": quote.ask1_price,
        "ask1_quantity": quote.ask1_quantity,
        "spread": spread,
        "spread_percent": spread_pct,
        "source_timestamp": quote.source_timestamp,
        "received_timestamp": quote.received_timestamp,
        "market_session": sess_status,
        "quote_display_eligible": quote_eligible,
        "data_source": data_source,
        "cache_state": cache_state,
        "provenance": data_source,
    }


def get_order_book(symbol: str) -> Dict[str, Any]:
    """
    Returns the currently available canonical top-3 order book depth from MarketState.
    Strictly read-only; does NOT manufacture depth beyond available fields.
    """
    if not symbol or not isinstance(symbol, str):
        return {
            "symbol": "",
            "status": "INVALID_ARGUMENT",
            "message": "Symbol must be a non-empty string.",
            "provenance": "APP_VALIDATION",
        }

    sym_clean = symbol.strip().upper()
    quote = market_state.get_quote(sym_clean)

    if not quote:
        return {
            "symbol": sym_clean,
            "status": "UNAVAILABLE",
            "message": f"No order book depth available in MarketState for {sym_clean}.",
            "provenance": "MARKET_STATE",
        }

    data_source = "REDIS_WARM_CACHE" if getattr(quote, "is_restored_from_cache", False) else "FIINQUANT_REALTIME"

    return {
        "symbol": sym_clean,
        "bids": [
            {"level": 1, "price": quote.bid1_price, "quantity": quote.bid1_quantity},
            {"level": 2, "price": quote.bid2_price, "quantity": quote.bid2_quantity},
            {"level": 3, "price": quote.bid3_price, "quantity": quote.bid3_quantity},
        ],
        "asks": [
            {"level": 1, "price": quote.ask1_price, "quantity": quote.ask1_quantity},
            {"level": 2, "price": quote.ask2_price, "quantity": quote.ask2_quantity},
            {"level": 3, "price": quote.ask3_price, "quantity": quote.ask3_quantity},
        ],
        "source_timestamp": quote.source_timestamp,
        "received_timestamp": quote.received_timestamp,
        "data_source": data_source,
        "provenance": data_source,
    }


def get_dashboard_snapshot(watched_symbols: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Returns the canonical market snapshot of all currently monitored primary instruments.
    Reads directly from in-memory MarketState without making new vendor subscription calls.
    """
    symbols_to_check = watched_symbols if (watched_symbols and len(watched_symbols) > 0) else DEFAULT_PRIMARY_UNIVERSE

    items = []
    for s in symbols_to_check:
        sym_clean = s.strip().upper()
        q = market_state.get_quote(sym_clean)
        inst_type = "CW" if (sym_clean.startswith("C") and len(sym_clean) >= 6) else ("INDEX" if sym_clean.startswith("VN") else "STOCK")

        spread: Optional[float] = None
        spread_pct: Optional[float] = None
        if q and q.bid1_price is not None and q.ask1_price is not None:
            diff = q.ask1_price - q.bid1_price
            if diff >= 0:
                spread = diff
                if q.bid1_price > 0:
                    spread_pct = diff / q.bid1_price

        items.append({
            "symbol": sym_clean,
            "instrument_type": inst_type,
            "last_price": q.last_price if q else None,
            "reference_price": q.reference_price if q else None,
            "change": q.price_change if q else None,
            "change_percent": q.price_change_percent if q else None,
            "bid1_price": q.bid1_price if q else None,
            "ask1_price": q.ask1_price if q else None,
            "spread": spread,
            "spread_percent": spread_pct,
            "total_volume": q.total_volume if q else None,
            "data_source": ("REDIS_WARM_CACHE" if getattr(q, "is_restored_from_cache", False) else "FIINQUANT_REALTIME") if q else "NONE",
            "is_available": q is not None,
        })

    sess_status = market_session.get_session_status().value
    quote_eligible = market_session.is_trading_active()

    return {
        "universe_size": len(items),
        "market_session": sess_status,
        "quote_display_eligible": quote_eligible,
        "instruments": items,
        "provenance": "MARKET_STATE",
    }
