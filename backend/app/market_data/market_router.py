import logging
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query

from app.market_data.market_schemas import (
    CanonicalQuote,
    HistoricalBar,
    MarketHealthResponse,
    HistoricalRangeLimitError,
    HistoricalAuthError,
    HistoricalCircuitOpenError,
    HistoricalEntitlementError,
    HistoricalRateLimitError,
    HistoricalUpstreamError,
    HistoricalTransportError,
    CIRCUIT_REASON_RATE_LIMIT,
)
from app.market_data.market_state import market_state
from app.market_data.market_subscription_manager import subscription_manager
from app.market_data.history_read_service import HistoryRequestError, history_read_service
from app.market_data.market_snapshot_resolver import market_snapshot_resolver
from app.market_data import trading_calendar as cal

logger = logging.getLogger(__name__)
from app.market_data.market_session import market_session

market_router = APIRouter(prefix="/api/market", tags=["Market Data"])

_MAX_DASHBOARD_SYMBOLS = 60


@market_router.get("/health", response_model=MarketHealthResponse)
async def market_health():
    """Sanitized operational health check for market data provider and warm cache."""
    health_data = subscription_manager.provider.get_health()
    store_health = await subscription_manager.store.health()
    sess_status = market_session.get_session_status().value
    sess_active = market_session.is_trading_active()

    return MarketHealthResponse(
        status="ok",
        provider=health_data.get("provider", "unknown"),
        authenticated=bool(health_data.get("authenticated", False)),
        upstream_status=str(health_data.get("upstream_status", "UNKNOWN")),
        trade_stream_connected=bool(health_data.get("trade_stream_connected", False)),
        bid_ask_stream_connected=bool(health_data.get("bid_ask_stream_connected", False)),
        subscription_count=len(subscription_manager.get_active_symbols()),
        max_subscriptions=subscription_manager.max_symbols,
        subscriptions=subscription_manager.get_active_symbols(),
        redis_enabled=bool(store_health.get("redis_enabled", False)),
        redis_connected=bool(store_health.get("redis_connected", False)),
        market_cache_available=bool(store_health.get("market_cache_available", False)),
        market_session=sess_status,
        market_session_active=sess_active,
        quote_display_eligible=sess_active,
    )


@market_router.get("/quote/{symbol}", response_model=CanonicalQuote)
async def get_market_quote(symbol: str):
    """Retrieves current in-memory canonical quote for a symbol."""
    sym = symbol.strip().upper()
    quote = market_state.get_quote(sym)
    if not quote:
        raise HTTPException(status_code=404, detail=f"Quote for symbol '{sym}' not found in active cache.")
    return quote


@market_router.get("/history/{symbol}", response_model=List[HistoricalBar])
async def get_historical_data(
    symbol: str,
    timeframe: str = Query(default="1D", description="Timeframe granularity (e.g. 1D)"),
    from_date: Optional[str] = Query(default=None, description="Start date (YYYY-MM-DD)"),
    to_date: Optional[str] = Query(default=None, description="End date (YYYY-MM-DD)"),
    adjusted: bool = Query(default=True, description="Whether historical prices are dividend/split adjusted"),
):
    """Retrieves historical price bars.

    PostgreSQL-first when the persistence layer is enabled (see HISTORY_SOURCE_MODE): a
    complete PostgreSQL hit makes zero provider calls; a legitimate missing in-horizon
    range triggers one controlled, single-flighted gap-fill. Otherwise (DB off, non-daily
    timeframe, unseeded symbol) the request is served directly from the provider. The
    response shape is identical either way.
    """
    sym = symbol.strip().upper()
    try:
        bars = await history_read_service.get_history(
            sym,
            timeframe=timeframe,
            from_date=from_date,
            to_date=to_date,
            adjusted=adjusted,
        )
        return bars
    except HistoryRequestError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HistoricalRangeLimitError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HistoricalCircuitOpenError as e:
        # circuit is open without contacting upstream; map by the reason it opened
        status = 429 if e.reason == CIRCUIT_REASON_RATE_LIMIT else 503
        raise HTTPException(status_code=status, detail=str(e))
    except HistoricalAuthError as e:
        raise HTTPException(status_code=503, detail=f"Market data provider authentication error: {e}")
    except HistoricalEntitlementError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except HistoricalRateLimitError:
        raise HTTPException(status_code=429, detail="Upstream provider rate limited")
    except (HistoricalUpstreamError, HistoricalTransportError) as e:
        raise HTTPException(status_code=503, detail=f"Upstream market data provider unavailable: {e}")
    except Exception as e:
        logger.error("Error fetching historical data for %s: %s", sym, e)
        raise HTTPException(status_code=500, detail=f"Failed to fetch historical data: {e}")


@market_router.get("/subscriptions")
async def get_subscriptions():
    """Returns desired and active realtime subscription lists + remaining capacity."""
    active = subscription_manager.get_active_symbols()
    return {
        "desired": subscription_manager.get_desired_symbols(),
        "active": active,
        "capacity": subscription_manager.max_symbols,
        "capacity_remaining": max(0, subscription_manager.max_symbols - len(active)),
    }


@market_router.get("/dashboard")
async def get_dashboard_rows(
    symbols: str = Query(..., description="Comma-separated symbols"),
    debug: bool = Query(default=False, description="Include the per-field fallback decision trace"),
):
    """Fully-resolved dashboard rows with an explicit temporal fallback.

    During an active session a symbol's row is LIVE. Outside trading hours (weekend,
    holiday, lunch, pre-open, post-close) it falls back to the last completed session's
    persisted snapshot, then to end-of-day daily bars, with each field group carrying a
    ``provenance`` block (state / source / asOf / sessionDate). Realtime-only fields with
    no legitimate fallback are ``null`` with ``state = UNAVAILABLE`` - never fabricated.
    """
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()][:_MAX_DASHBOARD_SYMBOLS]
    if not syms:
        raise HTTPException(status_code=400, detail="At least one symbol is required.")

    now = cal._as_vn(None)
    rows = await market_snapshot_resolver.resolve_rows(syms, now=now, diag=debug)
    tracked = set(subscription_manager.get_active_symbols())
    wire_rows = []
    for r in rows:
        w = r.to_wire()
        w["tracked_realtime"] = r.symbol in tracked
        wire_rows.append(w)

    return {
        "rows": wire_rows,
        "as_of": now.isoformat(),
        "market_session": cal.session_status(now).value,
        "market_session_active": cal.is_trading_active(now),
        "latest_completed_session": cal.latest_completed_trading_session(now).isoformat(),
        "calendar_confidence": cal.calendar_confidence(now.date()),
    }


@market_router.get("/_diag/{symbol}")
async def get_symbol_diagnostics(symbol: str):
    """Sanitized fallback-decision trace for one symbol: which source won each field group,
    which session it came from, whether a gap-fill fired. No provider payloads or secrets."""
    sym = symbol.strip().upper()
    now = cal._as_vn(None)
    rows = await market_snapshot_resolver.resolve_rows([sym], now=now, diag=True)
    r = rows[0]
    return {
        "symbol": sym,
        "as_of": now.isoformat(),
        "latest_completed_session": cal.latest_completed_trading_session(now).isoformat(),
        "market_session": cal.session_status(now).value,
        "decision": r.diag,
        "provenance": {
            "quote": r.quote_prov.to_wire(),
            "book": r.book_prov.to_wire(),
            **({"analytics": r.analytics_prov.to_wire()} if r.analytics_prov else {}),
        },
    }
