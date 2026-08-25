import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.ai.router import ai_router
from app.market.router import market_router
from app.market.websocket import ws_router
from app.market.subscription_manager import subscription_manager
from app.instruments.router import instruments_router
from app.instruments.registry import instrument_registry
from app.quant.router import quant_router
from app.quant.engine import live_quant_engine
from app.market.state import market_state
from app.market.websocket import manager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("cw-research-backend")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: initialize instrument registry, quant engine, and market data provider
    logger.info("Initializing CW Research Platform Backend...")
    try:
        await instrument_registry.initialize()
    except Exception as e:
        logger.warning(f"Instrument registry initialization warning: {e}")

    # Wire Quant Engine
    live_quant_engine.set_market_state_getter(lambda sym: market_state.get_quote(sym))
    live_quant_engine.set_broadcaster(manager.broadcast_analytics_patch)

    def on_market_state_change(sym: str, quote):
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(live_quant_engine.on_market_state_updated(sym, quote))
        except Exception:
            pass

    subscription_manager.register_update_listener(on_market_state_change)

    try:
        await subscription_manager.initialize()
    except Exception as e:
        logger.warning(f"Market provider initialization warning: {e}")
    yield
    # Shutdown: clean up streams
    logger.info("Shutting down CW Research Platform Backend...")
    try:
        await subscription_manager.shutdown()
    except Exception as e:
        logger.warning(f"Market provider shutdown warning: {e}")


app = FastAPI(
    title="CW Research Platform API",
    version="1.0.0",
    description="Quantitative Covered Warrant Research Terminal Gateway and AI Copilot Service",
    lifespan=lifespan,
)

# CORS middleware for local development and proxying
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount Routers
app.include_router(ai_router)
app.include_router(market_router)
app.include_router(instruments_router)
app.include_router(quant_router)
app.include_router(ws_router)


@app.get("/health", tags=["System"])
async def root_health():
    health_data = subscription_manager.provider.get_health()
    return {
        "status": "ok",
        "service": "cw-research-backend",
        "environment": settings.ENVIRONMENT,
        "ai_enabled": settings.AI_ENABLED,
        "market_provider": health_data.get("provider", "unknown"),
        "market_upstream_status": health_data.get("upstream_status", "UNKNOWN"),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=True)
