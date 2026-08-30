import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.core.config import settings
from app.core.production_guard import collect_production_problems, enforce_production_config
from app.security import (
    MaxBodySizeMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
    ai_call_gate,
    history_gapfill_gate,
    security_counters,
)
from app.security.rate_limiter import rate_limiter
from app.ai.ai_router import ai_router
from app.market_data.market_router import market_router
from app.market_data.market_websocket import ws_router
from app.market_data.market_subscription_manager import subscription_manager
from app.instruments.instrument_router import instruments_router
from app.instruments.instrument_registry import instrument_registry
from app.quant.quant_router import quant_router
from app.enrichment.router import research_router
from app.me import me_router
from app.quant.quant_engine import live_quant_engine
from app.quant.historical_volatility_service import historical_volatility_service
from app.persistence import database as persistence_db
from app.market_data.history_read_service import history_read_service
from app.market_data.market_state import market_state
from app.market_data.market_websocket import manager

import re

class SensitiveDataRedactor(logging.Filter):
    """
    Sanitizes log messages across all subsystems by masking Bearer tokens and credentials.
    """
    BEARER_PATTERN = re.compile(r"(Bearer\s+)[A-Za-z0-9_\-\.]+", re.IGNORECASE)
    AUTH_HEADER_PATTERN = re.compile(r"('Authorization':\s*'?Bearer\s+)[^']+'?", re.IGNORECASE)
    AUTH_RESULT_PATTERN = re.compile(r"(auth function result\s+)\S+", re.IGNORECASE)
    JWT_PATTERN = re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+", re.IGNORECASE)
    PASSWORD_PATTERN = re.compile(r"(password['\"]?\s*[:=]\s*['\"])[^'\"]+(['\"])", re.IGNORECASE)

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self.BEARER_PATTERN.sub(r"\1[REDACTED]", record.msg)
            record.msg = self.AUTH_HEADER_PATTERN.sub(r"\1[REDACTED]", record.msg)
            record.msg = self.AUTH_RESULT_PATTERN.sub(r"\1[REDACTED_TOKEN]", record.msg)
            record.msg = self.JWT_PATTERN.sub("[REDACTED_JWT]", record.msg)
            record.msg = self.PASSWORD_PATTERN.sub(r"\1[REDACTED]\2", record.msg)
        return True


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

# Suppress verbose vendor debug and transport frames.
# NOTE: signalrcore logs under the logger name "SignalRCoreClient" (see
# signalrcore.helpers.Helpers.get_logger), NOT "signalrcore". The FiinQuantX SDK also
# forcibly re-enables DEBUG on the root logger and on "SignalRCoreClient" every time it
# constructs a stream; FiinQuantProvider._tame_sdk_side_effects re-suppresses them after
# each stream operation at runtime.
logging.getLogger("SignalRCoreClient").setLevel(logging.WARNING)
logging.getLogger("signalrcore").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.INFO)
logging.getLogger("websockets").setLevel(logging.INFO)
logging.getLogger("websocket").setLevel(logging.WARNING)

# Apply redactor to root and existing handlers
_redactor = SensitiveDataRedactor()
for _h in logging.root.handlers:
    _h.addFilter(_redactor)
logging.root.addFilter(_redactor)

logger = logging.getLogger("cw-research-backend")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: initialize instrument registry, quant engine, and market data provider
    logger.info("Initializing CW Research Terminal Backend...")

    # ---- Public-API hardening (Step 10) + production fail-safe (Step 11 prep) ----
    # rate_limiter.configure() itself raises RateLimiterStartupError for an unsafe
    # production limiter config; the guard below is the single coherent check for
    # everything else. Both are no-ops when ENVIRONMENT != production.
    await rate_limiter.configure()
    ai_call_gate.set_limit(settings.AI_MAX_CONCURRENT)
    history_gapfill_gate.set_limit(settings.HISTORY_MAX_CONCURRENT_GAPFILLS)
    enforce_production_config(settings, rate_limiter_mode=rate_limiter.mode)

    try:
        await instrument_registry.initialize()
    except Exception as e:
        logger.warning(f"Instrument registry initialization warning: {e}")

    # Durable historical persistence (PostgreSQL). OFF unless DATABASE_ENABLED. Storage
    # foundation only - the realtime path and the public historical API do NOT depend on
    # it yet. A failed connection is non-fatal unless DATABASE_REQUIRE_ON_STARTUP is set.
    _persistence_ready = False
    if settings.DATABASE_ENABLED:
        try:
            await persistence_db.init_engine()
            await persistence_db.ping()
            _persistence_ready = True
            logger.info("PostgreSQL persistence layer: connected.")
            # Sweep ingestion_runs left RUNNING by a prior process exit / cancelled run
            # (e.g. a deploy, or the HV warm-up timeout cancelling an in-flight gap-fill).
            try:
                from app.persistence.repositories.ingestion_repository import IngestionRepository

                async with persistence_db.get_sessionmaker()() as _s, _s.begin():
                    _orphaned = await IngestionRepository(_s).fail_orphaned_runs()
                if _orphaned:
                    logger.warning("Marked %d orphaned RUNNING ingestion_run(s) as FAILED.", _orphaned)
            except Exception as _e:  # noqa: BLE001 - bookkeeping cleanup must never block startup
                logger.warning("Orphaned ingestion_run sweep skipped: %s", _e)
        except Exception as e:
            if settings.DATABASE_REQUIRE_ON_STARTUP:
                logger.error(f"PostgreSQL persistence required but unavailable: {e}")
                raise
            logger.warning(
                f"PostgreSQL persistence unavailable (non-fatal, DATABASE_REQUIRE_ON_STARTUP=false): "
                f"{e.__class__.__name__}: {e}"
            )

    # Wire Quant Engine
    live_quant_engine.startup()
    live_quant_engine.set_market_state_getter(lambda sym: market_state.get_quote(sym))
    live_quant_engine.set_broadcaster(manager.broadcast_analytics_patch)

    def on_market_state_change(sym: str, quote):
        # Synchronous, event-loop-thread hand-off. The engine records a latest-wins
        # generation and owns its own bounded task lifecycle - no create_task here.
        live_quant_engine.notify_market_tick(sym)

    subscription_manager.register_update_listener(on_market_state_change)

    try:
        await subscription_manager.initialize()
    except Exception as e:
        logger.warning(f"Market provider initialization warning: {e}")

    # ---- Historical read path (Step 7) ----
    # The direct provider is always available for provider-direct mode / non-daily / unseeded.
    history_read_service.set_provider(subscription_manager.provider)
    _snapshot_checkpointer = None
    if _persistence_ready:
        history_read_service.configure(
            engine=persistence_db.get_engine(),
            sessionmaker=persistence_db.get_sessionmaker(),
            provider=subscription_manager.provider,
        )
        logger.info("Historical reads: PostgreSQL-first (mode=%s).", settings.HISTORY_SOURCE_MODE)

        # ---- After-hours fallback resolver + last-valid snapshot checkpointer (Step 13C) ----
        from app.market_data.market_snapshot_resolver import market_snapshot_resolver
        from app.market_data.snapshot_checkpointer import SnapshotCheckpointer

        market_snapshot_resolver.configure(persistence_db.get_sessionmaker())
        _snapshot_checkpointer = SnapshotCheckpointer(
            persistence_db.get_sessionmaker(),
            subscription_manager.get_active_symbols,
        )
        _snapshot_checkpointer.start()
        app.state.snapshot_checkpointer = _snapshot_checkpointer
    else:
        logger.info("Historical reads: provider-direct (persistence not enabled/reachable).")

    # Wire the Historical Volatility Service AFTER the market provider is initialized so its
    # upstream historical source is usable. The engine getter (get_estimate) is a pure
    # in-memory lookup; all fetching happens here / in the background refresh loop / ensure().
    # Startup warm-up must never make the application fail to boot. When PostgreSQL has the
    # adjusted daily bars, HV warm-up makes ZERO historical FiinQuant calls.
    if _persistence_ready:
        from app.persistence.bar_source import PostgresHistoricalBarSource

        hv_source = PostgresHistoricalBarSource(
            persistence_db.get_sessionmaker(),
            gap_filler=history_read_service.ingestion_service(),
            min_bars_for_fill=settings.HV_POSTGRES_MIN_BARS_FOR_FILL,
        )
        historical_volatility_service.set_bar_source(hv_source)
        logger.info("Historical volatility source: PostgreSQL (PostgresHistoricalBarSource).")
    else:
        historical_volatility_service.set_bar_source(subscription_manager.provider)
    live_quant_engine.set_historical_vol_getter(historical_volatility_service.get_estimate)

    _startup_underlyings: list[str] = []
    try:
        _startup_underlyings = await instrument_registry.get_underlyings(active_only=True)
        warmed = await historical_volatility_service.warm(
            _startup_underlyings, timeout=settings.QUANT_HV_WARMUP_TIMEOUT_SECONDS
        )
        ready = sum(1 for v in warmed.values() if v is not None)
        logger.info(
            f"Historical volatility warm-up: {ready}/{len(_startup_underlyings)} underlyings ready "
            f"(window HV_{historical_volatility_service.window})."
        )
    except Exception as e:
        logger.warning(
            f"Historical volatility warm-up incomplete (non-fatal): {e.__class__.__name__}: {e}"
        )

    def _hv_refresh_symbols() -> list[str]:
        # Re-warm the startup universe plus anything ensure() has since pulled in.
        seen = set(_startup_underlyings) | set(historical_volatility_service.cached_underlyings())
        return sorted(seen)

    historical_volatility_service.start_periodic_refresh(_hv_refresh_symbols)

    yield
    # Shutdown: stop ingestion first (no new ticks), then drain the analytics scheduler,
    # then background refreshers.
    logger.info("Shutting down CW Research Terminal Backend...")
    try:
        await subscription_manager.shutdown()
    except Exception as e:
        logger.warning(f"Market provider shutdown warning: {e}")
    try:
        await live_quant_engine.shutdown()
    except Exception as e:
        logger.warning(f"Quant engine shutdown warning: {e}")
    try:
        await historical_volatility_service.stop_periodic_refresh()
    except Exception as e:
        logger.warning(f"Historical volatility refresh shutdown warning: {e}")
    try:
        if _snapshot_checkpointer is not None:
            await _snapshot_checkpointer.stop()
    except Exception as e:
        logger.warning(f"Snapshot checkpointer shutdown warning: {e}")
    try:
        await persistence_db.dispose_engine()
    except Exception as e:
        logger.warning(f"PostgreSQL persistence shutdown warning: {e}")


app = FastAPI(
    title="CW Research Terminal API",
    version="1.0.0",
    description="Quantitative Covered Warrant Research Terminal Gateway and AI Copilot Service",
    lifespan=lifespan,
)

# ------------------------------------------------------------------ #
# Middleware stack (Step 10). add_middleware prepends, so execution order is the
# REVERSE of the calls below:
#   TrustedHost -> SecurityHeaders -> CORS -> RateLimit -> MaxBodySize -> routes
# CORS wraps RateLimit so a 429 still carries Access-Control-Allow-Origin and the
# browser can read it. None of these touch the websocket scope.
# ------------------------------------------------------------------ #
_cors_origins = settings.cors_allowed_origins()

app.add_middleware(MaxBodySizeMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=bool(_cors_origins),  # credentials only with an explicit origin list
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
    expose_headers=["X-AI-Error-Code"],
    max_age=600,
)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts())

# Mount Routers
app.include_router(ai_router)
app.include_router(market_router)
app.include_router(instruments_router)
app.include_router(quant_router)
app.include_router(me_router)
app.include_router(ws_router)
app.include_router(research_router)


def _ai_daily_budget_snapshot() -> dict:
    try:
        from app.ai.ai_limits import ai_daily_budget

        return ai_daily_budget.snapshot()
    except Exception:  # noqa: BLE001
        return {"enabled": False}


@app.get("/healthz", tags=["System"], include_in_schema=False)
async def liveness():
    """Cheap liveness probe for the platform healthcheck. No I/O: a 200 means the
    process is up and the event loop is responsive. Readiness detail (DB, Redis,
    provider, security posture) lives on /health."""
    return {"status": "ok"}


@app.get("/health", tags=["System"])
async def root_health():
    health_data = subscription_manager.provider.get_health()
    store_health = await subscription_manager.store.health()
    from app.market_data.market_session import market_session
    sess_status = market_session.get_session_status().value
    sess_active = market_session.is_trading_active()

    def _cal_confidence() -> str:
        from app.market_data import trading_calendar as _c
        return _c.calendar_confidence(_c._as_vn(None).date())

    def _checkpointer_health() -> dict:
        cp = getattr(app.state, "snapshot_checkpointer", None)
        return cp.health() if cp is not None else {"enabled": False}

    return {
        "status": "ok",
        "service": "cw-research-backend",
        "environment": settings.ENVIRONMENT,
        "ai_enabled": settings.AI_ENABLED,
        "market_provider": health_data.get("provider", "unknown"),
        "market_upstream_status": health_data.get("upstream_status", "UNKNOWN"),
        "market_session": sess_status,
        "market_session_active": sess_active,
        "quote_display_eligible": sess_active,
        "redis_enabled": store_health.get("redis_enabled", False),
        "redis_connected": store_health.get("redis_connected", False),
        "market_cache_available": store_health.get("market_cache_available", False),
        "quant_scheduler": live_quant_engine.stats(),
        "database": await persistence_db.health(),
        "history_reads": history_read_service.health(),
        "calendar_confidence": _cal_confidence(),
        "snapshot_checkpointer": _checkpointer_health(),
        "auth": {
            "configured": settings.auth_configured(),
            "mode": (
                "asymmetric_jwks"
                if settings.SUPABASE_URL.strip()
                else "shared_secret"
                if settings.SUPABASE_JWT_SECRET.strip()
                else "disabled"
            ),
        },
        "security": {
            "rate_limit": rate_limiter.health(),
            "production_config_problems": len(
                collect_production_problems(settings, rate_limiter_mode=rate_limiter.mode)
            ),
            "ai_public_enabled": bool(settings.AI_ENABLED and settings.AI_PUBLIC_ENABLED),
            "public_realtime_enabled": bool(settings.PUBLIC_REALTIME_ENABLED),
            "cors_origins_configured": bool(settings.CORS_ALLOWED_ORIGINS.strip()),
            "allowed_hosts_enforced": bool(settings.ALLOWED_HOSTS.strip()),
            "hsts_enabled": bool(settings.SECURITY_HSTS_ENABLED),
            "client_ip_trust_mode": settings.client_ip_trust_mode(),
            "gates": {
                "ai_calls": {"limit": ai_call_gate.limit, "in_flight": ai_call_gate.in_flight},
                "history_gapfill": {
                    "limit": history_gapfill_gate.limit,
                    "in_flight": history_gapfill_gate.in_flight,
                },
            },
            "ai_daily_budget": _ai_daily_budget_snapshot(),
            "ws": {
                "active": manager.active_count,
                "max_total": settings.WS_MAX_CONNECTIONS_TOTAL,
                "max_per_client": settings.WS_MAX_CONNECTIONS_PER_IP,
            },
            "counters": security_counters.snapshot(),
        },
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=True)
