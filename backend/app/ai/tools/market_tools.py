"""
Read-Only Market Data Tools for Research Copilot.
Consumes the SAME canonical application services (MarketState, MarketSession, Redis warm-cache)
that power the UI WebSocket gateway.
"""

from typing import Dict, Any, Optional, List
import logging

from app.instruments.instrument_registry import instrument_registry
from app.market_data.market_state import market_state
from app.market_data.market_session import market_session
from app.market_data.trading_calendar import session_context
from app.market_data.market_subscription_manager import subscription_manager

logger = logging.getLogger(__name__)


def _live_universe() -> List[str]:
    """Symbols the terminal is currently tracking in MarketState (whatever is subscribed
    for this deployment) - no hardcoded ticker list."""
    try:
        return sorted(market_state.get_all_quotes().keys())
    except Exception:  # noqa: BLE001
        return []


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
        "market_phase": market_session.get_market_phase().value,
        "quote_display_eligible": quote_eligible,
        "gateway_connected": True,
        "authenticated": bool(health.get("authenticated", True)),
        "upstream_status": upstream_status,
        "cache_available": bool(subscription_manager.store.is_available()),
        "server_time_vn": vn_now.strftime("%Y-%m-%d %H:%M:%S (VN UTC+7)"),
        "provenance": "APP_MARKET_SESSION",
        "feedStatus": health.get("feedStatus"),
        "sessionContext": session_context(vn_now),
    }


def _row_payload(row) -> Dict[str, Any]:
    values = row.values
    bid, ask = values.get("bid1_price"), values.get("ask1_price")
    spread = ask - bid if bid is not None and ask is not None and ask >= bid else None
    midpoint = (bid + ask) / 2 if bid is not None and ask is not None and spread is not None else None
    return {
        "symbol": row.symbol, "instrument_type": row.instrument_type,
        "underlying_symbol": row.underlying_symbol or instrument_registry.underlying_of(row.symbol),
        **values,
        "change": values.get("price_change"), "change_percent": values.get("price_change_percent"),
        "spread": spread, "spread_percent": spread / midpoint if midpoint and spread is not None else None,
        "status": "AVAILABLE" if any(values.get(k) is not None for k in ("last_price", "bid1_price", "ask1_price")) else "UNAVAILABLE",
        "session_date": row.quote_prov.session_date,
        "quote_display_eligible": row.is_realtime_eligible,
        "data_source": row.quote_prov.source.value,
        "cache_state": row.quote_prov.state.value,
        "provenance": row.to_wire()["provenance"],
    }


async def get_quote(symbol: str) -> Dict[str, Any]:
    """Same resolved instrument view as REST/UI, in RAW VND and decimal percentages."""
    if not isinstance(symbol, str) or not symbol.strip():
        return {"symbol": "", "status": "INVALID_ARGUMENT", "message": "Symbol must be a non-empty string."}
    from app.market_data.market_snapshot_resolver import market_snapshot_resolver
    from app.market_data.trading_calendar import session_context
    rows = await market_snapshot_resolver.resolve_rows([symbol], enrich_snapshot_history=False)
    return {**_row_payload(rows[0]), "sessionContext": session_context()}


async def get_order_book(symbol: str) -> Dict[str, Any]:
    quote = await get_quote(symbol)
    if quote.get("status") == "INVALID_ARGUMENT":
        return quote
    return {**quote,
        "bids": [{"level": n, "price": quote.get(f"bid{n}_price"), "quantity": quote.get(f"bid{n}_quantity")} for n in (1, 2, 3)],
        "asks": [{"level": n, "price": quote.get(f"ask{n}_price"), "quantity": quote.get(f"ask{n}_quantity")} for n in (1, 2, 3)],
    }


async def get_dashboard_snapshot(watched_symbols: Optional[List[str]] = None, symbols: Optional[List[str]] = None) -> Dict[str, Any]:
    from app.market_data.market_snapshot_resolver import market_snapshot_resolver
    from app.market_data.trading_calendar import session_context
    symbols = watched_symbols or symbols or _live_universe()
    rows = await market_snapshot_resolver.resolve_rows(symbols, enrich_snapshot_history=False)
    items = [{**_row_payload(row), "is_available": row.quote_prov.source.value != "NONE"} for row in rows]
    return {"universe_size": len(items), "instruments": items,
            "sessionContext": session_context(), "provenance": "RESOLVED_INSTRUMENT_VIEW",
            "market_session": market_session.get_session_status().value,
            "quote_display_eligible": market_session.is_trading_active()}
