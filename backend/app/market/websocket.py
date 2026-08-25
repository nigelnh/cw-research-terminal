import json
import logging
from typing import Set, Dict, Any
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.market.state import market_state
from app.market.subscription_manager import subscription_manager

logger = logging.getLogger(__name__)
ws_router = APIRouter()


class MarketConnectionManager:
    def __init__(self):
        self._active_connections: Set[WebSocket] = set()
        subscription_manager.register_patch_listener(self.broadcast_patch_threadsafe)
        subscription_manager.register_status_listener(self.broadcast_status)

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._active_connections.add(websocket)

        # Emit hardened initial gateway & upstream status frame
        health = subscription_manager.provider.get_health()
        up_status = health.get("upstream_status", "UNKNOWN")
        is_live = (up_status == "LIVE")

        status_msg = {
            "type": "status",
            "gateway_connected": True,
            "authenticated": bool(health.get("authenticated", False)),
            "upstream_status": up_status,
            "connected": is_live,  # Backward-compatible boolean: True ONLY when genuinely LIVE
            "subscription_count": len(subscription_manager.get_active_symbols()),
            "message": f"Connected to CW Research Gateway ({up_status})",
        }
        await websocket.send_text(json.dumps(status_msg))

    def broadcast_status(self) -> None:
        """Broadcasts updated upstream status frame to all connected WebSocket clients."""
        if not self._active_connections:
            return

        health = subscription_manager.provider.get_health()
        up_status = health.get("upstream_status", "UNKNOWN")
        is_live = (up_status == "LIVE")

        status_msg = {
            "type": "status",
            "gateway_connected": True,
            "authenticated": bool(health.get("authenticated", False)),
            "upstream_status": up_status,
            "connected": is_live,
            "subscription_count": len(subscription_manager.get_active_symbols()),
            "message": f"Connected to CW Research Gateway ({up_status})",
        }
        payload_str = json.dumps(status_msg)
        for ws in list(self._active_connections):
            try:
                import asyncio
                loop = asyncio.get_running_loop()
                loop.create_task(ws.send_text(payload_str))
            except Exception:
                pass

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self._active_connections:
            self._active_connections.remove(websocket)

    async def send_personal_message(self, message: Dict[str, Any], websocket: WebSocket) -> None:
        try:
            await websocket.send_text(json.dumps(message))
        except Exception as e:
            logger.warning(f"Error sending message to websocket client: {e}")

    def broadcast_patch_threadsafe(self, patch_msg: Dict[str, Any]) -> None:
        """Invoked when SubscriptionManager receives a live patch from provider."""
        if not self._active_connections:
            return

        payload_str = json.dumps(patch_msg)
        dead_sockets = []

        for ws in list(self._active_connections):
            try:
                import asyncio
                loop = asyncio.get_running_loop()
                loop.create_task(ws.send_text(payload_str))
            except Exception:
                dead_sockets.append(ws)

        for ws in dead_sockets:
            self.disconnect(ws)

    def broadcast_analytics_patch(self, symbol: str, analytics_obj: Any) -> None:
        """Broadcasts normalized analytics patch for a Covered Warrant to all connected WebSocket clients."""
        if not self._active_connections:
            return

        analytics_dict = analytics_obj.model_dump(by_alias=True) if hasattr(analytics_obj, "model_dump") else dict(analytics_obj)
        analytics_msg = {
            "type": "analytics_patch",
            "symbol": symbol.upper(),
            "analytics": analytics_dict,
        }
        payload_str = json.dumps(analytics_msg)
        dead_sockets = []

        for ws in list(self._active_connections):
            try:
                import asyncio
                loop = asyncio.get_running_loop()
                loop.create_task(ws.send_text(payload_str))
            except Exception:
                dead_sockets.append(ws)

        for ws in dead_sockets:
            self.disconnect(ws)


manager = MarketConnectionManager()


@ws_router.websocket("/ws/market")
async def websocket_market_endpoint(websocket: WebSocket):
    from app.instruments.registry import instrument_registry
    from app.quant.engine import live_quant_engine

    await manager.connect(websocket)
    try:
        while True:
            raw_text = await websocket.receive_text()
            if not raw_text:
                continue

            try:
                msg = json.loads(raw_text)
            except json.JSONDecodeError:
                logger.warning(f"Malformed WebSocket message: {raw_text}")
                continue

            msg_type = msg.get("type")
            symbols = msg.get("symbols", [])

            if not isinstance(symbols, list):
                continue

            if msg_type == "subscribe":
                clean_syms = [str(s).upper() for s in symbols if str(s).strip()]
                replace = bool(msg.get("replace", False))
                if replace:
                    success, reason = subscription_manager.set_exact_subscriptions(clean_syms)
                else:
                    success, reason = subscription_manager.subscribe(clean_syms)

                # Register watched CWs with quant engine
                for sym in clean_syms:
                    if sym.startswith("C") and len(sym) == 8:
                        spec = await instrument_registry.get_instrument(sym)
                        if spec and spec.underlying_symbol:
                            live_quant_engine.register_watched_cw(sym, spec.underlying_symbol)

                # Deliver immediate snapshot for cached symbols
                cached_rows = market_state.get_snapshots(clean_syms)
                if cached_rows:
                    import time
                    now_ms = int(time.time() * 1000)
                    snap_msg = {
                        "type": "snapshots",
                        "rows": cached_rows,
                        "ts": now_ms,
                    }
                    await manager.send_personal_message(snap_msg, websocket)

                # Deliver cached analytics for watched CWs
                for sym in clean_syms:
                    cached_analytics = live_quant_engine.get_analytics(sym)
                    if cached_analytics and cached_analytics.is_available:
                        an_dict = cached_analytics.model_dump(by_alias=True)
                        an_msg = {
                            "type": "analytics_patch",
                            "symbol": sym,
                            "analytics": an_dict,
                        }
                        await manager.send_personal_message(an_msg, websocket)

            elif msg_type == "unsubscribe":
                clean_syms = [str(s).upper() for s in symbols if str(s).strip()]
                subscription_manager.unsubscribe(clean_syms)
                for sym in clean_syms:
                    live_quant_engine.unregister_watched_cw(sym)

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket client error: {e}")
        manager.disconnect(websocket)
