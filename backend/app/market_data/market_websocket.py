import asyncio
import json
import logging
import re
import time
from collections import defaultdict, deque
from typing import Set, Dict, Any, Iterable
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.config import settings
from app.market_data.market_session import market_session
from app.market_data.market_state import market_state
from app.market_data.market_subscription_manager import subscription_manager
from app.security.client_ip import resolve_client_ip
from app.security.observability import security_counters

logger = logging.getLogger(__name__)
ws_router = APIRouter()

# WS close codes
_CLOSE_POLICY = 1008        # policy violation (caps, rate)
_CLOSE_TOO_BIG = 1009       # message too large
_CLOSE_GOING_AWAY = 1001    # idle timeout
_CLOSE_TRY_LATER = 1013     # feature disabled / try again later
_SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9]{1,11}$")


class MarketConnectionManager:
    """
    Manages active frontend WebSocket client connections, delivers immediate
    in-memory snapshots on subscription, and broadcasts live incremental patches.
    """
    def __init__(self):
        self._active_connections: Set[WebSocket] = set()
        self._conn_by_ip: Dict[str, int] = defaultdict(int)
        self._client_subscriptions: Dict[WebSocket, Set[str]] = {}
        subscription_manager.register_patch_listener(self.broadcast_patch_threadsafe)
        subscription_manager.register_status_listener(self.broadcast_status)

    @property
    def active_count(self) -> int:
        return len(self._active_connections)

    def get_client_subscriptions(self, websocket: WebSocket) -> Set[str]:
        return set(self._client_subscriptions.get(websocket, set()))

    def update_client_subscriptions(
        self,
        websocket: WebSocket,
        symbols: Iterable[str],
        *,
        replace: bool,
    ) -> tuple[list[str], list[str], list[str]]:
        """Update one socket's interests without touching the provider universe.

        Returns ``(accepted_from_request, unavailable, current_interests)``.
        """
        requested = list(dict.fromkeys(symbols))
        eligible = set(subscription_manager.get_server_universe_symbols())
        accepted = [symbol for symbol in requested if symbol in eligible]
        unavailable = [symbol for symbol in requested if symbol not in eligible]
        current = set() if replace else set(self._client_subscriptions.get(websocket, set()))
        current.update(accepted)
        self._client_subscriptions[websocket] = current
        return accepted, unavailable, sorted(current)

    def remove_client_subscriptions(
        self, websocket: WebSocket, symbols: Iterable[str]
    ) -> list[str]:
        current = set(self._client_subscriptions.get(websocket, set()))
        current.difference_update(symbols)
        self._client_subscriptions[websocket] = current
        return sorted(current)

    def _status_message(self, websocket: WebSocket | None = None) -> Dict[str, Any]:
        health = subscription_manager.provider.get_health()
        up_status = health.get("upstream_status", "UNKNOWN")
        feed_fresh = health.get("feed_fresh")
        sess_status = market_session.get_session_status().value
        sess_active = market_session.is_trading_active()
        phase = market_session.get_market_phase().value
        session_date = market_session.get_vn_now().date().isoformat()
        universe_health = subscription_manager.get_universe_health()
        return {
            "type": "status",
            "gateway_connected": True,
            "authenticated": bool(health.get("authenticated", False)),
            "upstream_status": up_status,
            "connected": up_status == "LIVE" and feed_fresh is not False,
            "feed_fresh": feed_fresh,
            "last_trade_tick_at": health.get("last_trade_tick_at"),
            "last_book_tick_at": health.get("last_book_tick_at"),
            "last_tick_at": health.get("last_tick_at"),
            "signalr_decode_error_count": health.get("signalr_decode_error_count", 0),
            "signalr_reconnect_count": health.get("reconnect_count", 0),
            "market_session": sess_status,
            "market_session_date": session_date,
            "market_session_active": sess_active,
            "market_phase": phase,
            "cache_available": subscription_manager.store.is_available(),
            "quote_display_eligible": sess_active,
            "subscription_count": len(subscription_manager.get_active_symbols()),
            "realtime_universe": universe_health,
            "realtime_universe_symbols": subscription_manager.get_server_universe_symbols(),
            "client_subscription_count": (
                len(self._client_subscriptions.get(websocket, set())) if websocket is not None else None
            ),
            "message": f"Connected to CW Research Gateway ({up_status}, Session: {sess_status})",
        }

    async def connect(self, websocket: WebSocket) -> bool:
        """Apply the connection caps, then accept. Returns False (handshake refused) when a
        limit is hit or public realtime is disabled - the caller must not enter its loop."""
        if not settings.PUBLIC_REALTIME_ENABLED:
            security_counters.incr("ws.rejected_disabled_total")
            await websocket.close(code=_CLOSE_TRY_LATER)
            return False

        ip = resolve_client_ip(websocket)
        if len(self._active_connections) >= settings.WS_MAX_CONNECTIONS_TOTAL:
            security_counters.incr("ws.rejected_global_cap_total")
            logger.warning("WebSocket /ws/market rejected: global cap %d reached", settings.WS_MAX_CONNECTIONS_TOTAL)
            await websocket.close(code=_CLOSE_TRY_LATER)
            return False
        if self._conn_by_ip[ip] >= settings.WS_MAX_CONNECTIONS_PER_IP:
            security_counters.incr("ws.rejected_per_client_cap_total")
            logger.warning("WebSocket /ws/market rejected: per-client cap %d reached", settings.WS_MAX_CONNECTIONS_PER_IP)
            await websocket.close(code=_CLOSE_POLICY)
            return False

        await websocket.accept()
        self._active_connections.add(websocket)
        self._client_subscriptions[websocket] = set()
        self._conn_by_ip[ip] += 1
        websocket.scope["_cw_client_ip"] = ip
        security_counters.set_gauge("ws.active_connections", len(self._active_connections))
        client_str = f"{ip}:{websocket.client.port}" if websocket.client else "unknown"
        logger.info(
            "WebSocket /ws/market client connected (%s). Active count: %d",
            client_str, len(self._active_connections),
        )

        # Emit hardened initial gateway, session, and upstream status frame.
        await websocket.send_text(json.dumps(self._status_message(websocket)))
        return True

    async def _safe_send(self, ws: WebSocket, payload_str: str) -> None:
        """Asynchronously sends a payload string to a websocket client and prunes on failure."""
        try:
            await ws.send_text(payload_str)
        except Exception:
            self.disconnect(ws)

    def broadcast_status(self) -> None:
        """Broadcasts updated upstream status frame to all connected WebSocket clients."""
        if not self._active_connections:
            return

        for ws in list(self._active_connections):
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._safe_send(ws, json.dumps(self._status_message(ws))))
            except Exception:
                self.disconnect(ws)

    def disconnect(self, websocket: WebSocket) -> None:
        self._client_subscriptions.pop(websocket, None)
        if websocket in self._active_connections:
            self._active_connections.remove(websocket)
            ip = websocket.scope.get("_cw_client_ip") if hasattr(websocket, "scope") else None
            if ip is not None and self._conn_by_ip.get(ip, 0) > 0:
                self._conn_by_ip[ip] -= 1
                if self._conn_by_ip[ip] == 0:
                    self._conn_by_ip.pop(ip, None)
            security_counters.set_gauge("ws.active_connections", len(self._active_connections))
            logger.info(
                "WebSocket /ws/market client disconnected (%s). Active count: %d",
                ip or "unknown", len(self._active_connections),
            )

    async def send_personal_message(self, message: Dict[str, Any], websocket: WebSocket) -> None:
        try:
            await websocket.send_text(json.dumps(message))
        except Exception as e:
            logger.warning(f"Error sending message to websocket client: {e}")
            self.disconnect(websocket)

    def broadcast_patch_threadsafe(self, patch_msg: Dict[str, Any]) -> None:
        """Invoked when SubscriptionManager receives a live patch from provider."""
        if not self._active_connections:
            return

        symbol = str(patch_msg.get("symbol") or patch_msg.get("patch", {}).get("Symbol") or "").upper()
        if not symbol:
            return
        payload_str = json.dumps(patch_msg)
        for ws in list(self._active_connections):
            if symbol not in self._client_subscriptions.get(ws, set()):
                continue
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._safe_send(ws, payload_str))
            except Exception:
                self.disconnect(ws)

    def broadcast_analytics_patch(self, symbol: str, analytics_obj: Any) -> None:
        """Send normalized analytics only to clients interested in this warrant."""
        if not self._active_connections:
            return

        clean_symbol = symbol.upper()
        analytics_dict = analytics_obj.model_dump(by_alias=True) if hasattr(analytics_obj, "model_dump") else dict(analytics_obj)
        analytics_msg = {
            "type": "analytics_patch",
            "symbol": clean_symbol,
            "analytics": analytics_dict,
        }
        payload_str = json.dumps(analytics_msg)
        for ws in list(self._active_connections):
            if clean_symbol not in self._client_subscriptions.get(ws, set()):
                continue
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._safe_send(ws, payload_str))
            except Exception:
                self.disconnect(ws)


manager = MarketConnectionManager()


def _too_big(raw_text: str) -> bool:
    return len(raw_text.encode("utf-8", "ignore")) > settings.WS_MAX_MESSAGE_BYTES


class _MessageRate:
    """Per-connection sliding-window message-rate guard."""

    __slots__ = ("_times", "_burst", "_window")

    def __init__(self) -> None:
        self._times: deque[float] = deque()
        self._burst = int(settings.WS_MESSAGE_BURST)
        self._window = float(settings.WS_MESSAGE_WINDOW_SECONDS)

    def allow(self) -> bool:
        now = time.monotonic()
        cutoff = now - self._window
        while self._times and self._times[0] < cutoff:
            self._times.popleft()
        if len(self._times) >= self._burst:
            return False
        self._times.append(now)
        return True


def _normalize_client_symbols(values: list[Any]) -> tuple[list[str], list[str]]:
    """Strictly normalize client symbols without coercing arbitrary JSON values."""
    clean: list[str] = []
    invalid: list[str] = []
    seen: set[str] = set()
    for index, value in enumerate(values):
        if not isinstance(value, str):
            invalid.append(f"item[{index}]")
            continue
        symbol = value.strip().upper()
        if not _SYMBOL_RE.fullmatch(symbol):
            invalid.append(symbol or f"item[{index}]")
            continue
        if symbol not in seen:
            clean.append(symbol)
            seen.add(symbol)
    return clean, invalid


@ws_router.websocket("/ws/market")
async def websocket_market_endpoint(websocket: WebSocket):
    from app.quant.quant_engine import live_quant_engine

    if not await manager.connect(websocket):
        return

    rate = _MessageRate()
    malformed = 0
    try:
        while True:
            try:
                raw_text = await asyncio.wait_for(
                    websocket.receive_text(), timeout=settings.WS_IDLE_TIMEOUT_SECONDS
                )
            except (TimeoutError, asyncio.TimeoutError):
                security_counters.incr("ws.closed_idle_total")
                await websocket.close(code=_CLOSE_GOING_AWAY)
                break

            if not raw_text:
                continue
            if _too_big(raw_text):
                security_counters.incr("ws.rejected_oversized_msg_total")
                await websocket.close(code=_CLOSE_TOO_BIG)
                break
            if not rate.allow():
                security_counters.incr("ws.rejected_msg_rate_total")
                await websocket.close(code=_CLOSE_POLICY)
                break

            try:
                msg = json.loads(raw_text)
            except json.JSONDecodeError:
                malformed += 1
                security_counters.incr("ws.malformed_msg_total")
                if malformed > 10:
                    await websocket.close(code=_CLOSE_POLICY)
                    break
                continue
            if not isinstance(msg, dict):
                continue

            msg_type = msg.get("type")
            symbols = msg.get("symbols", [])

            if not isinstance(symbols, list):
                continue
            if msg_type == "subscribe":
                clean_syms, invalid_syms = _normalize_client_symbols(symbols)
                replace = msg.get("replace", True)
                if not isinstance(replace, bool):
                    await manager.send_personal_message(
                        {
                            "type": "error",
                            "error": "invalid_replace",
                            "detail": "subscribe.replace must be a boolean",
                        },
                        websocket,
                    )
                    continue

                eligible = set(subscription_manager.get_server_universe_symbols())
                requested_eligible = set(clean_syms).intersection(eligible)
                proposed = requested_eligible if replace else (
                    manager.get_client_subscriptions(websocket).union(requested_eligible)
                )
                if len(proposed) > settings.WS_MAX_SYMBOLS_PER_CLIENT:
                    security_counters.incr("ws.rejected_symbol_count_total")
                    await manager.send_personal_message(
                        {
                            "type": "error",
                            "error": "too_many_symbols",
                            "detail": f"At most {settings.WS_MAX_SYMBOLS_PER_CLIENT} active interests per client.",
                        },
                        websocket,
                    )
                    continue

                accepted, unavailable, current = manager.update_client_subscriptions(
                    websocket, clean_syms, replace=replace
                )
                acknowledgement = {
                    "type": "subscription_ack",
                    "operation": "subscribe",
                    "replace": replace,
                    "requested_symbols": clean_syms,
                    "accepted_symbols": accepted,
                    "outside_symbols": unavailable,
                    "rejected_symbols": invalid_syms,
                    "subscribed_symbols": current,
                    "unavailable_symbols": unavailable,
                    "invalid_symbols": invalid_syms,
                    "realtime_universe_size": len(eligible),
                }

                # Centralized hydration of missing symbols from warm cache with session freshness checks
                if accepted:
                    await subscription_manager.hydrate_missing_market_state(accepted)

                # Deliver immediate snapshot for cached symbols
                cached_rows = market_state.get_snapshots(accepted)
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
                for sym in accepted:
                    cached_analytics = live_quant_engine.get_analytics(sym)
                    if cached_analytics and cached_analytics.is_available:
                        an_dict = cached_analytics.model_dump(by_alias=True)
                        an_msg = {
                            "type": "analytics_patch",
                            "symbol": sym,
                            "analytics": an_dict,
                        }
                        await manager.send_personal_message(an_msg, websocket)

                # Preserve the legacy snapshot-first ordering while still giving every
                # request an explicit result.  Clients with no cached data receive this
                # acknowledgement immediately.
                await manager.send_personal_message(acknowledgement, websocket)

            elif msg_type == "ping":
                # Keep the browser delivery socket alive and refresh the session/feed
                # state. This never changes per-client interests or the upstream universe.
                await manager.send_personal_message(
                    manager._status_message(websocket), websocket
                )

            elif msg_type == "unsubscribe":
                clean_syms, invalid_syms = _normalize_client_symbols(symbols)
                before = manager.get_client_subscriptions(websocket)
                removed = sorted(before.intersection(clean_syms))
                current = manager.remove_client_subscriptions(websocket, clean_syms)
                eligible = set(subscription_manager.get_server_universe_symbols())
                await manager.send_personal_message(
                    {
                        "type": "subscription_ack",
                        "operation": "unsubscribe",
                        "requested_symbols": clean_syms,
                        "removed_symbols": removed,
                        "subscribed_symbols": current,
                        "outside_symbols": [sym for sym in clean_syms if sym not in eligible],
                        "rejected_symbols": invalid_syms,
                        "unavailable_symbols": [sym for sym in clean_syms if sym not in eligible],
                        "invalid_symbols": invalid_syms,
                        "realtime_universe_size": len(eligible),
                    },
                    websocket,
                )

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WebSocket client error: {e}")
    finally:
        # Every exit path - client disconnect, error, OR a server-side `break`
        # (idle timeout, oversized/rate-limited/malformed-flood close) - must release
        # the connection slot and per-IP counter. disconnect() is idempotent.
        manager.disconnect(websocket)
