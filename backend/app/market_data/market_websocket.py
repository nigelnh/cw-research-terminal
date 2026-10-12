import asyncio
import json
import logging
import re
import time
from collections import defaultdict, deque
from typing import Set, Dict, Any, Callable, Iterable
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.config import settings
from app.market_data.market_session import market_session
from app.market_data.market_state import market_state
from app.market_data.trading_calendar import session_context
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

# With nothing material changed, a status frame goes out at most this often (see
# broadcast_status). A real change goes out at once.
STATUS_HEARTBEAT_SECONDS = 5.0
# Fields that move on every provider report without changing anything a client acts on:
# clocks (the browser runs its own from the last serverTime), tick stamps, diagnostic
# counters, and the per-client fields. They ride along with the next frame that goes out.
_STATUS_VOLATILE_FIELDS = frozenset({
    "serverTime", "checkedAt", "lastDataAt",
    "last_trade_tick_at", "last_book_tick_at", "last_tick_at",
    "signalr_decode_error_count", "signalr_reconnect_count",
    "client_subscription_count", "realtime_universe_symbols",
})


def _material(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _material(v) for k, v in value.items() if k not in _STATUS_VOLATILE_FIELDS}
    if isinstance(value, list):
        return [_material(v) for v in value]
    return value


def status_signature(message: Dict[str, Any]) -> str:
    """What a status frame says once its clocks, tick stamps and counters are set aside."""
    return json.dumps(_material(message), sort_keys=True, default=str)


class MarketConnectionManager:
    """
    Manages active frontend WebSocket client connections, delivers immediate
    in-memory snapshots on subscription, and broadcasts live incremental patches.
    """
    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._active_connections: Set[WebSocket] = set()
        self._conn_by_ip: Dict[str, int] = defaultdict(int)
        self._client_subscriptions: Dict[WebSocket, Set[str]] = {}
        # The realtime universe list each client was last sent (see _status_for).
        self._client_universe: Dict[WebSocket, list[str]] = {}
        self._clock = clock
        self._sent_status_signature: str | None = None
        self._sent_status_at = float("-inf")
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

    def _status_message(self, websocket: WebSocket) -> Dict[str, Any]:
        """One client's status frame, as of now."""
        return self._status_for(
            websocket, self._status_base(), subscription_manager.get_server_universe_symbols()
        )

    def _status_for(
        self, websocket: WebSocket, base: Dict[str, Any], universe: list[str]
    ) -> Dict[str, Any]:
        """`base` for one client. The universe list is most of the frame (370 symbols), so
        a client gets it only when it does not have this one yet: on connect and after the
        universe changes. A frame without it leaves the client's copy as it was."""
        message = {
            **base,
            "client_subscription_count": len(self._client_subscriptions.get(websocket, set())),
        }
        if self._client_universe.get(websocket) != universe:
            message["realtime_universe_symbols"] = universe
            self._client_universe[websocket] = universe
        return message

    def _status_base(self) -> Dict[str, Any]:
        """The part of the status frame every client shares."""
        health = subscription_manager.provider.get_health()
        up_status = health.get("upstream_status", "UNKNOWN")
        feed_fresh = health.get("feed_fresh")
        sess_status = market_session.get_session_status().value
        sess_active = market_session.is_trading_active()
        phase = market_session.get_market_phase().value
        context = session_context(market_session.get_vn_now())
        session_date = context["displaySessionDate"]
        universe_health = subscription_manager.get_universe_health()
        return {
            "type": "status",
            "sessionContext": context,
            "feedStatus": health.get("feedStatus"),
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
        """Send the status frame when something a client acts on changed, else a heartbeat.

        The provider reports its health after every realtime frame - 40 to 70 a second in
        a busy session - and each report used to reach every browser as a full status
        frame. Every one re-rendered the session-context consumers: on 2026-10-12 that was
        half of the browser's main thread, in stalls of up to 210 ms that swallowed the
        300 ms value flashes. The frames differed only in their clocks and tick stamps.
        """
        if not self._active_connections:
            return
        base = self._status_base()
        universe = subscription_manager.get_server_universe_symbols()
        signature = status_signature(base)
        now = self._clock()
        clients = list(self._active_connections)
        if (
            signature == self._sent_status_signature
            and now - self._sent_status_at < STATUS_HEARTBEAT_SECONDS
            and all(self._client_universe.get(ws) == universe for ws in clients)
        ):
            return
        self._sent_status_signature = signature
        self._sent_status_at = now
        for ws in clients:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(
                    self._safe_send(ws, json.dumps(self._status_for(ws, base, universe)))
                )
            except Exception:
                self.disconnect(ws)

    def disconnect(self, websocket: WebSocket) -> None:
        self._client_subscriptions.pop(websocket, None)
        self._client_universe.pop(websocket, None)
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
                    # Keep quote + analytics atomic on initial hydration. The engine only
                    # returns a value when its session and exact price tuple still match
                    # canonical market state; a real price change therefore omits this
                    # field until the corresponding recalculation is published.
                    for row in cached_rows:
                        symbol = str(row.get("Symbol") or "").upper()
                        analytics = live_quant_engine.get_analytics(
                            symbol, validate_inputs=True
                        )
                        if analytics is not None and analytics.is_available:
                            row["analytics"] = analytics.model_dump(mode="json")
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
                    cached_analytics = live_quant_engine.get_analytics(
                        sym, validate_inputs=True
                    )
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
