import logging
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query

from app.market_data.market_schemas import (
    CanonicalQuote,
    HistoricalBar,
    MarketHealthResponse,
    HistoricalRangeLimitError,
    HistoricalAuthError,
    HistoricalEntitlementError,
    HistoricalRateLimitError,
    HistoricalUpstreamError,
    HistoricalTransportError,
)
from app.market_data.market_state import market_state
from app.market_data.market_subscription_manager import subscription_manager

logger = logging.getLogger(__name__)
from app.market_data.market_session import market_session

market_router = APIRouter(prefix="/api/market", tags=["Market Data"])


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
    """Retrieves historical price bars from the active market provider."""
    sym = symbol.strip().upper()
    try:
        bars = await subscription_manager.provider.get_historical_bars(
            symbol=sym,
            timeframe=timeframe,
            from_date=from_date,
            to_date=to_date,
            adjusted=adjusted,
        )
        return bars
    except HistoricalRangeLimitError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HistoricalAuthError as e:
        raise HTTPException(status_code=503, detail=f"Market data provider authentication error: {e}")
    except HistoricalEntitlementError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except HistoricalRateLimitError as e:
        raise HTTPException(status_code=429, detail="Upstream provider rate limited")
    except (HistoricalUpstreamError, HistoricalTransportError) as e:
        raise HTTPException(status_code=503, detail=f"Upstream market data provider unavailable: {e}")
    except Exception as e:
        logger.error("Error fetching historical data for %s: %s", sym, e)
        raise HTTPException(status_code=500, detail=f"Failed to fetch historical data: {e}")


@market_router.get("/subscriptions")
async def get_subscriptions():
    """Returns desired and active subscription lists."""
    return {
        "desired": subscription_manager.get_desired_symbols(),
        "active": subscription_manager.get_active_symbols(),
        "capacity": subscription_manager.max_symbols,
    }
