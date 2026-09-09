import logging
import re
from typing import Any, Dict, List, Optional
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
    StockProfilesResponse,
    CIRCUIT_REASON_RATE_LIMIT,
)
from app.market_data.market_state import market_state
from app.market_data.traded_log import traded_log
from app.market_data.market_subscription_manager import subscription_manager
from app.market_data.history_read_service import HistoryRequestError, history_read_service
from app.market_data.market_snapshot_resolver import market_snapshot_resolver
from app.market_data.market_overview_service import market_overview_service
from app.instruments.instrument_registry import instrument_registry
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
    universe_health = subscription_manager.get_universe_health()
    sess_status = market_session.get_session_status().value
    sess_active = market_session.is_trading_active()

    return MarketHealthResponse(
        status="ok",
        sessionContext=cal.session_context(),
        feedStatus=health_data.get("feedStatus"),
        provider=health_data.get("provider", "unknown"),
        authenticated=bool(health_data.get("authenticated", False)),
        transport_mode=str(health_data.get("transport_mode", "UNKNOWN")),
        access_tier=str(health_data.get("access_tier", "UNVERIFIED")),
        api_key_configured=bool(health_data.get("api_key_configured", False)),
        license_verified=health_data.get("license_verified"),
        upstream_status=str(health_data.get("upstream_status", "UNKNOWN")),
        trade_stream_connected=bool(health_data.get("trade_stream_connected", False)),
        bid_ask_stream_connected=bool(health_data.get("bid_ask_stream_connected", False)),
        subscription_count=len(subscription_manager.get_active_symbols()),
        max_subscriptions=subscription_manager.max_symbols,
        subscriptions=subscription_manager.get_active_symbols(),
        redis_enabled=bool(store_health.get("redis_enabled", False)),
        redis_connected=bool(store_health.get("redis_connected", False)),
        market_cache_available=bool(store_health.get("market_cache_available", False)),
        market_cache_counters=store_health.get("counters", {}),
        feed_fresh=bool(health_data.get("feed_fresh", False)),
        last_trade_tick_at=health_data.get("last_trade_tick_at"),
        last_book_tick_at=health_data.get("last_book_tick_at"),
        last_tick_at=health_data.get("last_tick_at"),
        signalr_decode_error_count=int(health_data.get("signalr_decode_error_count", 0)),
        signalr_reconnect_count=int(health_data.get("reconnect_count", 0)),
        silent_stream_reconnect_count=int(health_data.get("silent_stream_reconnect_count", 0)),
        stream_watchdog_active=bool(health_data.get("stream_watchdog_active", False)),
        stream_silence_reconnect_seconds=float(health_data.get("stream_silence_reconnect_seconds", 0.0)),
        trade_tick_age_seconds=health_data.get("trade_tick_age_seconds"),
        request_count=int(health_data.get("request_count", 0)),
        request_failure_count=int(health_data.get("request_failure_count", 0)),
        quote_poll_seconds=health_data.get("quote_poll_seconds"),
        latest_board_check_age_seconds=health_data.get("latest_board_check_age_seconds"),
        tape_sweep_seconds=health_data.get("tape_sweep_seconds"),
        min_request_interval_seconds=health_data.get("min_request_interval_seconds"),
        realtime_source=health_data.get("realtime_source"),
        realtime_socket_connected=bool(health_data.get("realtime_socket_connected", False)),
        realtime_message_age_seconds=health_data.get("realtime_message_age_seconds"),
        realtime_message_count=int(health_data.get("realtime_message_count", 0)),
        realtime_quote_count=int(health_data.get("realtime_quote_count", 0)),
        realtime_parse_error_count=int(health_data.get("realtime_parse_error_count", 0)),
        realtime_reconnect_count=int(health_data.get("realtime_reconnect_count", 0)),
        realtime_session=health_data.get("realtime_session"),
        realtime_observed_symbols=health_data.get("realtime_observed_symbols", []),
        realtime_observed_stock_count=int(health_data.get("realtime_observed_stock_count", 0)),
        realtime_observed_cw_count=int(health_data.get("realtime_observed_cw_count", 0)),
        realtime_universe=universe_health,
        market_session=sess_status,
        market_session_active=sess_active,
        market_phase=market_session.get_market_phase().value,
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
    rows = await market_snapshot_resolver.resolve_rows(
        syms,
        now=now,
        diag=debug,
        enrich_snapshot_history=False,
    )
    tracked = set(subscription_manager.get_active_symbols())
    in_server_universe = getattr(subscription_manager, "is_in_server_universe", None)
    wire_rows = []
    for r in rows:
        w = r.to_wire()
        w["tracked_realtime"] = (
            bool(in_server_universe(r.symbol))
            if callable(in_server_universe)
            else r.symbol in tracked
        )
        wire_rows.append(w)

    return {
        "rows": wire_rows,
        "as_of": now.isoformat(),
        "sessionContext": cal.session_context(now),
        "feedStatus": subscription_manager.provider.get_health().get("feedStatus"),
        "market_session": cal.session_status(now).value,
        "market_session_active": cal.is_trading_active(now),
        "market_phase": cal.market_phase(now).value,
        "latest_completed_session": cal.latest_completed_trading_session(now).isoformat(),
        "calendar_confidence": cal.calendar_confidence(now.date()),
    }


@market_router.get("/dashboard/analytics")
async def get_dashboard_analytics(
    symbols: str = Query(..., description="Comma-separated symbols"),
):
    """CW analytics companion read that never blocks the dashboard quote snapshot."""
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()][:_MAX_DASHBOARD_SYMBOLS]
    if not syms:
        raise HTTPException(status_code=400, detail="At least one symbol is required.")

    now = cal._as_vn(None)
    rows = await market_snapshot_resolver.resolve_analytics_rows(syms, now=now)
    return {
        "rows": rows,
        "as_of": now.isoformat(),
        "sessionContext": cal.session_context(now),
        "feedStatus": subscription_manager.provider.get_health().get("feedStatus"),
        "market_session": cal.session_status(now).value,
        "market_session_active": cal.is_trading_active(now),
        "latest_completed_session": cal.latest_completed_trading_session(now).isoformat(),
    }


@market_router.get("/stock-profiles", response_model=StockProfilesResponse)
async def get_stock_profiles(symbols: str = Query(..., max_length=1000)):
    syms = sorted({s.strip().upper() for s in symbols.split(",") if s.strip()})
    if not syms or len(syms) > 60 or any(not re.fullmatch(r"[A-Z][A-Z0-9]{1,11}", s) for s in syms):
        raise HTTPException(status_code=400, detail="Provide between 1 and 60 valid stock symbols")
    provider_rows = []
    try:
        provider_rows = await subscription_manager.provider.get_stock_profiles(syms)
    except Exception as exc:  # entitlement and provider failures both fall through to PostgreSQL
        logger.warning("Provider stock profiles unavailable; using persisted profiles: %s", exc)

    persisted = {}
    try:
        from app.enrichment import repository as enrichment_repo
        from app.persistence import database as persistence_db

        if persistence_db.is_configured():
            async with persistence_db.get_sessionmaker()() as session:
                persisted = await enrichment_repo.get_company_profiles(session, syms)
    except Exception as exc:  # noqa: BLE001 - each item still gets a truthful unavailable row
        logger.warning("Persisted stock profile fallback unavailable: %s", exc)

    provider_by_symbol = {
        str(row.get("symbol", "")).strip().upper(): row
        for row in provider_rows
        if isinstance(row, dict) and row.get("symbol")
    }
    items = []
    for symbol in syms:
        upstream = provider_by_symbol.get(symbol, {})
        fallback = persisted.get(symbol)
        fallback_name = None
        fallback_exchange = None
        if fallback is not None:
            fallback_name = fallback.en_name or fallback.vn_name
            fallback_exchange = fallback.exchange
        name = upstream.get("name") or fallback_name
        short_name = upstream.get("short_name")
        exchange = upstream.get("exchange") or fallback_exchange
        used_provider = any(upstream.get(key) for key in ("name", "short_name", "exchange"))
        used_fallback = fallback is not None and (
            (not upstream.get("name") and bool(fallback_name))
            or (not upstream.get("exchange") and bool(fallback_exchange))
        )
        provider_source = str(upstream.get("source") or "VNSTOCK").upper()
        sources = ([provider_source] if used_provider else []) + (
            [str(fallback.source or "COMPANY_PROFILES").upper()] if used_fallback else []
        )
        populated = sum(value is not None for value in (name, short_name, exchange))
        availability = (
            "AVAILABLE" if name is not None and exchange is not None
            else "PARTIAL" if populated
            else "UNAVAILABLE"
        )
        items.append({
            "symbol": symbol,
            "name": name,
            "short_name": short_name,
            "exchange": str(exchange).upper() if exchange else None,
            "source": "+".join(dict.fromkeys(sources)) or None,
            "availability": availability,
        })
    return {"items": items}


@market_router.get("/fundamentals/{symbol}")
async def get_fundamentals(symbol: str):
    """Valuation and recent quarterly statement lines for one equity.

    Deliberately partial, and says which parts and why. The active provider supplies only
    fields that can be traced to its current company-ratio response.
    """
    sym = symbol.strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9]{1,11}", sym):
        raise HTTPException(status_code=400, detail=f"invalid symbol: {symbol!r}")

    valuation: Dict[str, Any] = {}
    quarters: List[Dict[str, Any]] = []
    errors: List[str] = []
    try:
        valuation = (await subscription_manager.provider.get_stock_valuation([sym])).get(sym, {})
    except Exception as exc:  # noqa: BLE001 - a partial answer beats a 500
        logger.warning("Valuation unavailable for %s: %s", sym, exc)
        errors.append("valuation")
    try:
        quarters = await subscription_manager.provider.get_financial_ratios(sym)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Financial ratios unavailable for %s: %s", sym, exc)
        errors.append("ratios")

    latest = quarters[-1] if quarters else {}
    available_metrics = {
        field: latest.get(field)
        for field in ("eps", "roe", "roa", "roic", "gross_margin")
    }
    latest_period = latest.get("period")
    provenance = {
        "pe": {"source": "VNSTOCK_VCI_RATIO_SUMMARY", "as_of": valuation.get("as_of")},
        "pb": {"source": "VNSTOCK_VCI_RATIO_SUMMARY", "as_of": valuation.get("as_of")},
        "eps": {"source": latest.get("statement_source"), "as_of": latest_period},
        "revenue": {"source": latest.get("statement_source"), "as_of": latest_period},
        "net_profit": {"source": latest.get("statement_source"), "as_of": latest_period},
        "roe": {"source": latest.get("ratio_source"), "as_of": latest_period},
        "roa": {"source": latest.get("ratio_source"), "as_of": latest_period},
        "roic": {"source": latest.get("ratio_source"), "as_of": latest_period},
        "gross_margin": {"source": latest.get("ratio_source"), "as_of": latest_period},
        "net_margin": {"source": latest.get("ratio_source") or latest.get("statement_source"),
                       "as_of": latest_period},
    }
    return {
        "symbol": sym,
        "pe": valuation.get("pe"),
        "pb": valuation.get("pb"),
        "valuation_as_of": valuation.get("as_of"),
        "net_margin": latest.get("net_margin"),
        **available_metrics,
        "latest_period": latest_period,
        "quarters": quarters,
        # Named, not silently blank: the UI shows the reason on each empty row.
        "unavailable": {
            field: "not served by the current market-data source"
            for field in ("eps", "roe", "roa", "roic", "gross_margin")
            if available_metrics.get(field) is None
        },
        "provenance": provenance,
        "source": "VNSTOCK_VCI",
        "errors": errors,
    }


@market_router.get("/overview")
async def get_market_overview():
    """Market-wide research strip; cached provider reads, no subscription mutations."""
    try:
        active_cws = await instrument_registry.search(active_only=True)
        return await market_overview_service.get([item.symbol for item in active_cws])
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc))
    except Exception as exc:
        logger.warning("Market overview unavailable: %s", exc)
        raise HTTPException(status_code=503, detail="Market overview is temporarily unavailable")


@market_router.get("/trades/{symbol}")
async def get_traded_log(symbol: str, limit: int = Query(default=200, ge=1, le=8000)):
    """Time & sales for one instrument.

    Served from the shared Redis tape, so a browser opening mid-session on any machine gets
    the whole session's prints and not just what has arrived since it connected. Kept until
    08:00 ICT the morning after its session, so the panel still has the day's tape after the
    close. `side` is DERIVED from the last known book (see traded_log), not published by the
    exchange - `side_basis` says so on every response.
    """
    sym = symbol.strip().upper()
    if not (1 <= len(sym) <= 12) or not sym.isalnum():
        raise HTTPException(status_code=400, detail=f"invalid symbol: {symbol!r}")
    payload = await traded_log.get_session(sym, limit=limit)
    # A symbol may be opened after its background sweep slot, or the backend may have
    # restarted mid-session before Redis was attached. Repair an empty tape from the
    # provider's confirmed intraday endpoint; never synthesize prints from a board/daily
    # snapshot. The provider caps this read, and its own scope/backoff contains failures.
    if not payload.get("items"):
        try:
            raw_prints = await subscription_manager.provider.get_confirmed_trade_prints(
                sym, limit=min(limit, 1000)
            )
            added = []
            quote = market_state.get_quote(sym)
            for raw in raw_prints:
                item = traded_log.record_provider_print(sym, raw, quote=quote)
                if item is not None:
                    added.append(item)
            if added:
                await traded_log.persist_many(sym, added)
                payload = await traded_log.get_session(sym, limit=limit)
        except NotImplementedError:
            pass
        except Exception as exc:  # noqa: BLE001 - an empty partial tape is still a 200
            logger.debug("Traded-log on-demand backfill unavailable for %s: %s", sym, type(exc).__name__)
    payload["sessionContext"] = cal.session_context()
    payload["market_session"] = cal.session_status(cal._as_vn(None)).value
    return payload


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
        "sessionContext": cal.session_context(now),
        "feedStatus": subscription_manager.provider.get_health().get("feedStatus"),
        "latest_completed_session": cal.latest_completed_trading_session(now).isoformat(),
        "market_session": cal.session_status(now).value,
        "market_phase": cal.market_phase(now).value,
        "decision": r.diag,
        "provenance": {
            "quote": r.quote_prov.to_wire(),
            "book": r.book_prov.to_wire(),
            "reference": r.reference_prov.to_wire(),
            **({"analytics": r.analytics_prov.to_wire()} if r.analytics_prov else {}),
        },
    }
