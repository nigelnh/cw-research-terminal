import logging
import asyncio
import threading
import time
import io
import contextlib
from typing import Iterator, List, Dict, Any, Optional, Callable, Set
from datetime import datetime, timedelta

from app.core.config import settings
from app.market_data.market_session import market_session
from app.market_data.market_schemas import (
    CIRCUIT_REASON_AUTH,
    CIRCUIT_REASON_RATE_LIMIT,
    CIRCUIT_REASON_UNKNOWN,
    HistoricalBar,
    HistoricalDataError,
    HistoricalRangeLimitError,
    HistoricalAuthError,
    HistoricalCircuitOpenError,
    HistoricalEntitlementError,
    HistoricalRateLimitError,
    HistoricalTransportError,
    HistoricalUpstreamError,
)
from app.market_data.providers.base_market_provider import MarketDataProvider

logger = logging.getLogger(__name__)

# The signalrcore library (bundled with FiinQuantX) logs under this name, and the SDK's
# stream ctor forcibly re-enables DEBUG on it and on the root logger.
_SIGNALR_LOGGER_NAME = "SignalRCoreClient"
_NOISY_LOGGERS = (_SIGNALR_LOGGER_NAME, "signalrcore", "websocket", "websockets", "urllib3")


def _looks_like_ping_checker(obj: Any) -> bool:
    """Duck-type test for a signalrcore ``ConnectionStateChecker`` (the keep-alive/ping loop)."""
    return (
        obj is not None
        and hasattr(obj, "running")
        and hasattr(obj, "ping_function")
        and hasattr(obj, "keep_alive_interval")
    )


def _iter_signalr_ping_checkers() -> Iterator[Any]:
    """Yield every live ``ConnectionStateChecker``-shaped object currently owning a thread."""
    for th in list(threading.enumerate()):
        owner: Any = getattr(getattr(th, "_target", None), "__self__", None)
        if _looks_like_ping_checker(owner):
            yield owner


def count_signalr_ping_threads() -> int:
    return sum(1 for cc in _iter_signalr_ping_checkers() if getattr(cc, "running", False))


def reap_orphan_signalr_ping_threads(exclude: Optional[Set[int]] = None) -> int:
    """Force-stop leaked signalrcore keep-alive/ping loops.

    WORKAROUND for a FiinQuantX + signalrcore limitation (see module notes / provider
    docstring): ``<stream>.stop()`` only tears the hub connection down when
    ``self.connected`` is True, so a server-closed socket leaves the
    ``ConnectionStateChecker`` thread alive, endlessly sending ``PingMessage`` on a dead
    socket ("Connection closed / Socket closed by the server" every second). The SDK's
    internal reconnect also builds fresh hub connections without reliably retiring the old
    one, so these accumulate. ``.running`` is a plain bool the loop polls each second, so
    clearing it makes the daemon thread exit within ~1s.

    ``exclude`` is a set of ``id()``s of checkers that must be left running (the ones
    owned by the provider's currently-active streams).
    """
    exclude = exclude or set()
    reaped = 0
    for cc in _iter_signalr_ping_checkers():
        if id(cc) in exclude or not getattr(cc, "running", False):
            continue
        try:
            cc.running = False
            stop = getattr(cc, "stop", None)
            if callable(stop):
                stop()
        except Exception:  # noqa: BLE001 - defensive; this is a best-effort reaper
            pass
        reaped += 1
    return reaped


class FiinQuantProvider(MarketDataProvider):
    """Production market-data provider wrapping the FiinQuant SDK (FiinQuantX) SignalR streams.

    SignalR lifecycle invariant
    ---------------------------
    **At any moment there is at most one active SignalR connection lifecycle owned by this
    one provider instance.** All lifecycle transitions (``connect`` / ``disconnect`` /
    ``set_subscriptions``) are serialised by ``_lifecycle_lock`` and tagged with a
    monotonic ``_generation``. Every stream this provider creates is tracked in
    ``_owned_streams`` and is *fully retired* - keep-alive/ping loop stopped, socket
    closed, SDK reconnect disabled, leaking log handler detached - before a replacement is
    created or the provider disconnects.

    Third-party limitations mitigated here (cannot be fixed in the obfuscated SDK):
      * ``FiinQuantX.core.Trading_Data_Stream`` / ``BidAsk`` ``__init__`` call
        ``logging.getLogger().setLevel(DEBUG)`` and attach an unbounded-growth
        ``CustomHandler`` to the ROOT logger on every construction. ``_tame_sdk_side_effects``
        undoes this after every stream operation.
      * ``<stream>.stop()`` skips ``hub_connection.stop()`` unless ``self.connected`` -
        so a server-closed socket orphans the ping thread. ``_hard_stop_stream_sync`` +
        ``reap_orphan_signalr_ping_threads`` force it down at the transport boundary.
      * The SDK's internal ``_handle_disconnect`` reconnect loop builds new hub
        connections without retiring the old ones. The reaper sweeps those up on every
        retire/disconnect.
    """

    def __init__(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
        max_symbols: Optional[int] = None,
    ):
        self.username = username or settings.FIINQUANT_USERNAME
        self.password = password or settings.FIINQUANT_PASSWORD
        self.max_symbols = max_symbols or settings.FIINQUANT_MAX_REALTIME_SYMBOLS

        self._session: Any = None
        self._trade_stream: Any = None
        self._bidask_stream: Any = None
        self._active_symbols: List[str] = []
        self._event_callback: Optional[Callable[[str, Dict[str, Any], str], None]] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._is_connected = False
        self._upstream_status = "DISCONNECTED"
        self._last_error: Optional[str] = None

        # ---- SignalR lifecycle ownership ----
        self._lifecycle_lock = asyncio.Lock()
        self._generation = 0
        self._shutting_down = False
        self._owned_streams: List[Any] = []          # the SDK stream objects we currently own
        self._connect_count = 0
        self._disconnect_count = 0
        self._stream_restart_count = 0
        self._orphans_reaped = 0

        # ---- Adapter-owned Reconnect State ----
        self._reconnect_task: Optional[asyncio.Task] = None
        self._reconnect_backoff_index: int = 0
        self._reconnect_backoffs = (1.0, 2.0, 4.0, 8.0, 15.0, 30.0)
        # Outside an active HOSE session FiinQuant closes the subscription streams within
        # seconds, so the in-session fast backoff would reconnect ~every 10s indefinitely.
        # Off-session we instead poll at this cadence, but never sleep past the next
        # session open (see ``_compute_reconnect_delay``). Injectable for deterministic tests.
        self._off_session_reconnect_seconds: float = 300.0
        self._market_is_active: Callable[[], bool] = market_session.is_trading_active
        self._seconds_to_next_session: Callable[[], float] = (
            market_session.seconds_until_next_trading_session
        )

        # ---- Historical provider health & circuit breaker ----
        self._historical_circuit_open_until: float = 0.0
        self._historical_circuit_reason: Optional[str] = None
        self._historical_last_status: str = "HEALTHY"
        self._historical_last_error: Optional[str] = None
        self._historical_consecutive_auth_errors: int = 0
        self._overview_lock = asyncio.Lock()
        self._overview_cache: Optional[Dict[str, Any]] = None
        self._overview_cache_at: float = 0.0
        self._stock_profile_lock = asyncio.Lock()
        self._stock_profile_cache: Dict[str, tuple[float, Dict[str, Any]]] = {}

    def set_event_callback(self, callback: Callable[[str, Dict[str, Any], str], None]) -> None:
        self._event_callback = callback
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None

    def _ensure_loop(self) -> None:
        if self._loop is None or self._loop.is_closed():
            try:
                self._loop = asyncio.get_running_loop()
            except RuntimeError:
                pass

    def _on_trade_raw(self, data: Any) -> None:
        """Callback invoked by FiinQuant SDK Trading_Data_Stream on worker thread."""
        try:
            d = data.to_dict() if hasattr(data, "to_dict") else (data if isinstance(data, dict) else vars(data))
            sym = str(d.get("Ticker", "")).upper()
            if not sym:
                return
            self._ensure_loop()
            if self._loop and self._loop.is_running() and self._event_callback:
                self._loop.call_soon_threadsafe(self._event_callback, "trade", d, sym)
        except Exception as err:
            logger.warning(f"Error handling raw trade event: {err}")

    def _on_bidask_raw(self, data: Any) -> None:
        """Callback invoked by FiinQuant SDK BidAsk stream on worker thread."""
        try:
            d = data.to_dict() if hasattr(data, "to_dict") else (data if isinstance(data, dict) else vars(data))
            sym = str(d.get("Ticker", "")).upper()
            if not sym:
                return
            self._ensure_loop()
            if self._loop and self._loop.is_running() and self._event_callback:
                self._loop.call_soon_threadsafe(self._event_callback, "bidask", d, sym)
        except Exception as err:
            logger.warning(f"Error handling raw BidAsk event: {err}")

    # ------------------------------------------------------------------ #
    # SDK seam (overridden in tests; the only place real FiinQuant auth happens)
    # ------------------------------------------------------------------ #
    def _create_session(self) -> Any:
        """Synchronous: authenticate and return a logged-in FiinQuantX session, or ``None``."""
        try:
            import FiinQuantX as fq  # type: ignore
            session = fq.FiinSession(username=self.username, password=self.password)
            session.login()
            ok = getattr(session, "is_login", False) or bool(getattr(session, "access_token", None))
            return session if ok else None
        except Exception as e:  # noqa: BLE001
            logger.error(f"FiinQuant authentication error: {e.__class__.__name__}")
            return None

    # ------------------------------------------------------------------ #
    # Connect / disconnect (serialised, idempotent)
    # ------------------------------------------------------------------ #
    async def connect(self) -> bool:
        async with self._lifecycle_lock:
            return await self._connect_locked()

    async def _connect_locked(self) -> bool:
        if not self.username or not self.password:
            logger.warning("FiinQuant credentials not configured in environment.")
            self._upstream_status = "UNAVAILABLE"
            return False
        if self._shutting_down:
            return False
        if self._session is not None and getattr(self._session, "is_login", False) and self._is_connected:
            return True  # idempotent: already authenticated with a live valid session

        self._ensure_loop()
        session = await asyncio.to_thread(self._create_session)
        self._tame_sdk_side_effects()

        if session is not None:
            self._session = session
            self._is_connected = True
            self._upstream_status = "CONNECTED"
            self._generation += 1
            self._connect_count += 1
            logger.info(
                "FiinQuant authentication successful (connection generation %d). Upstream: CONNECTED",
                self._generation,
            )
            return True

        self._session = None
        self._is_connected = False
        self._upstream_status = "ERROR"
        logger.error("FiinQuant authentication failed.")
        return False

    async def disconnect(self) -> None:
        """Retire every owned stream and the session. Idempotent; safe under shutdown/reload."""
        async with self._lifecycle_lock:
            self._shutting_down = True
            self._upstream_status = "DISCONNECTED"
            self._is_connected = False
            if self._reconnect_task is not None and not self._reconnect_task.done():
                self._reconnect_task.cancel()
                self._reconnect_task = None
            await self._retire_streams_locked()
            self._session = None
            self._active_symbols = []
            self._trade_stream = None
            self._bidask_stream = None
            self._disconnect_count += 1
            logger.info(
                "FiinQuant provider disconnected (generation %d, %d orphan ping threads reaped over lifetime).",
                self._generation, self._orphans_reaped,
            )

    # ------------------------------------------------------------------ #
    # Stream retirement & startup
    # ------------------------------------------------------------------ #
    async def _retire_streams_locked(self) -> None:
        """Fully retire every stream this provider owns. Cancel-safe and time-bounded."""
        streams = list(self._owned_streams)
        self._owned_streams.clear()

        try:
            for s in streams:
                self._hard_stop_stream_sync(s)
            self._orphans_reaped += reap_orphan_signalr_ping_threads()

            if streams:
                def _sdk_stop_all() -> None:
                    for s in streams:
                        try:
                            s.stop()
                        except Exception as e:  # noqa: BLE001
                            logger.debug("SDK stream.stop() error: %s", e)

                try:
                    await asyncio.wait_for(asyncio.to_thread(_sdk_stop_all), timeout=5.0)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    logger.warning(
                        "SDK stream.stop() did not complete in 5s; ping loops already reaped, "
                        "daemon threads will exit."
                    )
                self._orphans_reaped += reap_orphan_signalr_ping_threads()
        finally:
            self._trade_stream = None
            self._bidask_stream = None
            self._tame_sdk_side_effects()

    def _hard_stop_stream_sync(self, stream: Any) -> None:
        """Aggressive, synchronous teardown of one FiinQuantX stream. Never raises."""
        try:
            ev = getattr(stream, "_stop_event", None)
            if ev is not None and hasattr(ev, "set"):
                ev.set()
        except Exception:  # noqa: BLE001
            pass
        try:
            stream._stop = True
        except Exception:  # noqa: BLE001
            pass

        hub = getattr(stream, "hub_connection", None)
        transport = getattr(hub, "transport", None) if hub is not None else None
        if transport is not None:
            for attr, val in (("manually_closing", True), ("reconnection_handler", None)):
                try:
                    setattr(transport, attr, val)
                except Exception:  # noqa: BLE001
                    pass
            cc: Any = getattr(transport, "connection_checker", None)
            if _looks_like_ping_checker(cc):
                try:
                    cc.running = False
                    if callable(getattr(cc, "stop", None)):
                        cc.stop()
                except Exception:  # noqa: BLE001
                    pass
            ws = getattr(transport, "_ws", None)
            if ws is not None and callable(getattr(ws, "close", None)):
                try:
                    ws.close()
                except Exception:  # noqa: BLE001
                    pass

        handler = getattr(stream, "custom_handler", None)
        if handler is not None:
            try:
                logging.getLogger().removeHandler(handler)
            except Exception:  # noqa: BLE001
                pass

    def _tame_sdk_side_effects(self) -> None:
        """Undo FiinQuantX's global logging hijack after any stream operation."""
        root = logging.getLogger()
        try:
            if root.level < logging.INFO:
                root.setLevel(logging.INFO)
        except Exception:  # noqa: BLE001
            pass
        for name in _NOISY_LOGGERS:
            try:
                logging.getLogger(name).setLevel(logging.WARNING)
            except Exception:  # noqa: BLE001
                pass
        live_handler_ids = {id(getattr(s, "custom_handler", None)) for s in self._owned_streams}
        for h in list(root.handlers):
            if h.__class__.__name__ == "CustomHandler" and id(h) not in live_handler_ids:
                try:
                    root.removeHandler(h)
                except Exception:  # noqa: BLE001
                    pass

    def _disable_sdk_reconnect_guarded(self, stream: Any, gen: int) -> None:
        """Proactively disables signalrcore auto-reconnect and SDK unmanaged reconnect loops
        with runtime compatibility checks.
        """
        # 1. Disable signalrcore transport auto-reconnect
        hub = getattr(stream, "hub_connection", None)
        transport = getattr(hub, "transport", None) if hub is not None else None
        if transport is not None:
            if hasattr(transport, "reconnection_handler"):
                transport.reconnection_handler = None
            else:
                logger.warning("FiinQuantX SignalR transport missing expected reconnection_handler attribute.")

            # Register transport close notification to trigger single provider-owned reconnect
            if hub is not None and hasattr(hub, "on_close") and callable(getattr(hub, "on_close", None)):
                try:
                    hub.on_close(lambda: self._on_stream_closed_callback(gen))
                except Exception as e:
                    logger.warning("Could not register on_close callback on hub: %s", e)
        else:
            logger.warning("FiinQuantX stream missing expected hub_connection or transport.")

        # 2. Neutralize SDK unmanaged thread reconnect loop (_handle_disconnect)
        if hasattr(stream, "_handle_disconnect"):
            try:
                setattr(stream, "_handle_disconnect", lambda: None)
            except Exception as e:
                logger.warning("Could not neutralize stream._handle_disconnect: %s", e)
        else:
            logger.warning("FiinQuantX stream missing expected _handle_disconnect hook.")

    def _on_stream_closed_callback(self, gen: int) -> None:
        """Callback invoked on worker thread when SignalR transport drops."""
        if self._shutting_down or gen != self._generation or not self._active_symbols:
            return
        self._ensure_loop()
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._schedule_reconnect)

    def _schedule_reconnect(self) -> None:
        if self._shutting_down or not self._active_symbols:
            return
        if self._reconnect_task is not None and not self._reconnect_task.done():
            return
        self._ensure_loop()
        if self._loop and self._loop.is_running():
            self._reconnect_task = self._loop.create_task(self._reconnect_worker())

    def _compute_reconnect_delay(self) -> float:
        """Seconds to wait before the next reconnect attempt.

        During an active HOSE session: the existing fast bounded backoff - a stream that
        drops mid-session is a real failure worth retrying hard.

        Outside the session (pre-open, lunch, post-close, weekend): FiinQuant tears the
        subscription streams down within seconds, so a fast retry just loops forever. Poll
        at ``_off_session_reconnect_seconds`` instead - but never sleep past the next
        session open, so the provider is back LIVE when trading resumes. This only changes
        the *pacing* of reconnects; it never stops them, and it never blocks a cold start
        (startup goes through ``connect`` / ``set_subscriptions``, not this worker).
        """
        base = self._reconnect_backoffs[min(self._reconnect_backoff_index, len(self._reconnect_backoffs) - 1)]
        try:
            if self._market_is_active():
                return base
            secs_to_open = max(0.0, float(self._seconds_to_next_session()))
        except Exception:  # noqa: BLE001 - never let a calendar bug wedge reconnect
            return base
        return max(base, min(self._off_session_reconnect_seconds, secs_to_open))

    async def _reconnect_worker(self) -> None:
        """Single-flighted, bounded-backoff reconnect loop owned exclusively by FiinQuantProvider."""
        delay = self._compute_reconnect_delay()
        logger.info(
            "SignalR stream disconnected. Scheduling provider reconnect in %.1fs "
            "(generation %d, session_active=%s)...",
            delay, self._generation, self._market_is_active(),
        )
        await asyncio.sleep(delay)

        async with self._lifecycle_lock:
            if self._shutting_down or not self._active_symbols:
                return

            self._upstream_status = "RESTARTING"
            await self._retire_streams_locked()

            # Reuse existing authenticated session if still valid; only re-authenticate if session is dead/invalid
            is_valid_session = self._session is not None and getattr(self._session, "is_login", False)
            if not is_valid_session:
                logger.info("FiinQuant session invalid/expired. Re-authenticating for reconnect...")
                if not await self._connect_locked():
                    self._reconnect_backoff_index += 1
                    self._upstream_status = "ERROR"
                    self._schedule_reconnect()
                    return

            gen = self._generation
            self._stream_restart_count += 1
            err = await asyncio.to_thread(self._start_new_streams_sync, self._active_symbols, gen)
            self._tame_sdk_side_effects()

            if not self._owned_streams or err:
                self._reconnect_backoff_index += 1
                self._upstream_status = "ERROR"
                self._last_error = err
                logger.error("SignalR stream reconnect attempt failed: %s", err)
                self._schedule_reconnect()
                return

            self._reconnect_backoff_index = 0
            self._upstream_status = "CONNECTED"
            self._last_error = None
            logger.info(
                "SignalR stream reconnect successful for %d symbols (generation %d).",
                len(self._active_symbols), gen,
            )

    async def set_subscriptions(self, symbols: List[str]) -> bool:
        """Replace the active streaming subscription set. Serialised; retires old streams first."""
        async with self._lifecycle_lock:
            if self._shutting_down:
                return False

            clean_symbols = list(dict.fromkeys([s.strip().upper() for s in symbols if s.strip()]))
            if len(clean_symbols) > self.max_symbols:
                logger.error(
                    "Requested %d symbols exceeds capacity %d", len(clean_symbols), self.max_symbols
                )
                return False

            if self._session is None or not self._is_connected:
                if not await self._connect_locked():
                    return False

            self._ensure_loop()
            self._upstream_status = "RESTARTING"

            # Fully retire the current streams BEFORE creating replacements.
            await self._retire_streams_locked()

            if not clean_symbols:
                self._active_symbols = []
                self._upstream_status = "CONNECTED"
                return True
            if self._shutting_down:
                return False

            self._last_error = None
            self._stream_restart_count += 1
            gen = self._generation

            err = await asyncio.to_thread(self._start_new_streams_sync, clean_symbols, gen)
            self._last_error = err
            self._tame_sdk_side_effects()

            if not self._owned_streams:
                self._upstream_status = "ERROR"
                logger.error("FiinQuant stream startup failed (generation %d): %s", gen, err)
                return False

            self._active_symbols = clean_symbols
            self._upstream_status = "CONNECTED"
            logger.info(
                "FiinQuant streams active for %d symbols (generation %d): %s",
                len(clean_symbols), gen, clean_symbols,
            )
            return True

    def _start_new_streams_sync(self, clean_symbols: List[str], gen: int) -> Optional[str]:
        """Runs in a worker thread. Stores stream refs into ``self`` IMMEDIATELY."""
        try:
            ba_symbols = [s for s in clean_symbols if s not in ("VNINDEX", "VN30", "HNXINDEX", "UPCOM")]

            trade = self._session.Trading_Data_Stream(tickers=clean_symbols, callback=self._on_trade_raw)
            if hasattr(trade, "_handle_disconnect"):
                try:
                    setattr(trade, "_handle_disconnect", lambda: None)
                except Exception:
                    pass
            trade.start()
            self._trade_stream = trade
            self._owned_streams.append(trade)

            if ba_symbols:
                bidask = self._session.BidAsk(tickers=ba_symbols, callback=self._on_bidask_raw)
                if hasattr(bidask, "_handle_disconnect"):
                    try:
                        setattr(bidask, "_handle_disconnect", lambda: None)
                    except Exception:
                        pass
                bidask.start()
                self._bidask_stream = bidask
                self._owned_streams.append(bidask)

            # Proactively disable broken SDK / signalrcore competing reconnect paths with compatibility guards
            for s in [trade, self._bidask_stream]:
                if s is not None:
                    self._disable_sdk_reconnect_guarded(s, gen)

            return None
        except Exception as e:  # noqa: BLE001
            err = f"{e.__class__.__name__}: {e}"
            logger.error("Failed to start FiinQuant streams for %s: %s", clean_symbols, err)
            return err

    def get_active_subscriptions(self) -> List[str]:
        return list(self._active_symbols)

    def get_health(self) -> Dict[str, Any]:
        trade_conn = getattr(self._trade_stream, "connected", False) if self._trade_stream else False
        ba_conn = getattr(self._bidask_stream, "connected", False) if self._bidask_stream else False

        if not self._is_connected:
            computed_status = "UNAVAILABLE" if not self.username or not self.password else "ERROR"
        elif self._last_error or self._upstream_status == "ERROR":
            computed_status = "ERROR"
        elif self._upstream_status == "RESTARTING":
            computed_status = "RESTARTING"
        elif not self._active_symbols:
            computed_status = "READY"
        elif trade_conn or ba_conn:
            computed_status = "LIVE"
        else:
            computed_status = "DISCONNECTED"

        return {
            "provider": "fiinquant",
            "authenticated": self._is_connected,
            "upstream_status": computed_status,
            "trade_stream_connected": trade_conn,
            "bid_ask_stream_connected": ba_conn,
            "subscription_count": len(self._active_symbols),
            "max_subscriptions": self.max_symbols,
            "subscriptions": self.get_active_subscriptions(),
            "last_error": self._last_error,
            # ---- SignalR lifecycle observability ----
            "connection_generation": self._generation,
            "active_stream_count": len(self._owned_streams),
            "signalr_ping_threads": count_signalr_ping_threads(),
            "is_shutting_down": self._shutting_down,
            "connect_count": self._connect_count,
            "disconnect_count": self._disconnect_count,
            "stream_restart_count": self._stream_restart_count,
            "orphan_ping_threads_reaped": self._orphans_reaped,
            # ---- Historical health observability ----
            "historical_status": self._historical_last_status,
            "historical_circuit_open": time.monotonic() < self._historical_circuit_open_until,
            "historical_last_error": self._historical_last_error,
        }

    async def get_historical_bars(
        self,
        symbol: str,
        timeframe: str = "1D",
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        adjusted: bool = True,
    ) -> List[HistoricalBar]:
        """Fetches historical EOD bars via FiinQuant Fetch_Trading_Data.

        Raises typed errors for range limits, auth/entitlement failures, rate limits, and transport drops.
        Does NOT silently truncate explicit caller ranges.
        """
        sym = symbol.strip().upper()
        tf_norm = timeframe.strip().lower()
        if tf_norm in ("1d", "daily", "d"):
            by_param = "1d"
            default_days = 360  # Safe ~360 days default lookback (~247 trading sessions)
        elif tf_norm in ("5m", "5min"):
            by_param = "5m"
            default_days = 5
        elif tf_norm in ("30m", "30min"):
            by_param = "30m"
            default_days = 15
        elif tf_norm in ("15m", "15min"):
            by_param = "15m"
            default_days = 10
        elif tf_norm in ("1h", "60m"):
            by_param = "1h"
            default_days = 30
        elif tf_norm in ("1m", "1min"):
            by_param = "1m"
            default_days = 2
        else:
            by_param = "1d"
            default_days = 360

        default_from = (datetime.now() - timedelta(days=default_days)).strftime("%Y-%m-%d")
        f_date = from_date or default_from
        t_date = to_date or datetime.now().strftime("%Y-%m-%d")

        # Range verification: if explicit range > 365 calendar days, raise HistoricalRangeLimitError (do NOT clamp silently)
        if from_date is not None:
            try:
                dt_from = datetime.strptime(f_date, "%Y-%m-%d").date()
                dt_to = datetime.strptime(t_date, "%Y-%m-%d").date() if to_date else datetime.now().date()
                span_days = (dt_to - dt_from).days
                now_date = datetime.now().date()
                lookback_days = (now_date - dt_from).days
                if span_days > 365 or lookback_days > 365:
                    raise HistoricalRangeLimitError(
                        f"Historical request for {sym} ({f_date} to {t_date}) exceeds upstream timeframe limit "
                        f"(requested lookback: {max(span_days, lookback_days)} days; upstream maximum: 365 days). "
                        f"Use multi-window range chunking for longer lookbacks."
                    )
            except ValueError:
                pass  # allow non-standard format strings to pass to upstream validation

        # Circuit breaker check: if the historical circuit is open, reject immediately
        # without hitting upstream. The typed error carries the canonical reason the
        # circuit opened so callers decide retryability without inspecting message strings.
        now_mono = time.monotonic()
        if self._historical_circuit_open_until > now_mono:
            reason = self._historical_circuit_reason or CIRCUIT_REASON_UNKNOWN
            rem = self._historical_circuit_open_until - now_mono
            raise HistoricalCircuitOpenError(
                f"Historical market data provider circuit breaker is OPEN ({reason}). "
                f"Next retry allowed in ~{int(rem) + 1}s.",
                reason=reason,
                retry_after_seconds=rem,
            )

        if not self._session or not self._is_connected:
            connected = await self.connect()
            if not connected:
                self._historical_last_status = "DEGRADED"
                self._historical_last_error = "Authentication failed"
                self._historical_circuit_open_until = time.monotonic() + 60.0
                self._historical_circuit_reason = CIRCUIT_REASON_AUTH
                raise HistoricalAuthError(f"FiinQuant authentication failed while fetching historical bars for {sym}")

        def _fetch() -> List[HistoricalBar]:
            captured_output = io.StringIO()
            try:
                with contextlib.redirect_stdout(captured_output), contextlib.redirect_stderr(captured_output):
                    res = self._session.Fetch_Trading_Data(
                        realtime=False,
                        tickers=[sym],
                        fields=["open", "high", "low", "close", "volume"],
                        by=by_param,
                        from_date=f_date,
                        to_date=t_date,
                        adjusted=adjusted,
                    )
                    df = res.get_data() if hasattr(res, "get_data") else res

                captured_text = captured_output.getvalue()
                if (df is None or len(df) == 0) and captured_text:
                    if "TimeFrameLimitFailed" in captured_text or "365 days" in captured_text:
                        raise HistoricalRangeLimitError(f"Upstream timeframe limit exceeded for {sym}: {captured_text}")
                    if "401" in captured_text or "invalid_token" in captured_text or "Unauthorized" in captured_text:
                        raise RuntimeError(f"401 Unauthorized: {captured_text}")
                    if "403" in captured_text or "Forbidden" in captured_text:
                        raise RuntimeError(f"403 Forbidden: {captured_text}")
                    if "429" in captured_text or "RateLimit" in captured_text:
                        raise RuntimeError(f"429 RateLimit: {captured_text}")
                    if any(c in captured_text for c in ("500", "502", "503", "504", "timeout", "Timeout")):
                        raise RuntimeError(f"Upstream error: {captured_text}")

                bars: List[HistoricalBar] = []

                if df is not None and hasattr(df, "to_dict"):
                    records = df.to_dict(orient="records")
                    for r in records:
                        d_str = str(r.get("timestamp") or r.get("TradingDate") or r.get("date") or "")
                        c_val = r.get("close") or r.get("Close")
                        if d_str and c_val is not None:
                            bars.append(
                                HistoricalBar(
                                    date=d_str,
                                    open=float(r.get("open") or r.get("Open") or c_val),
                                    high=float(r.get("high") or r.get("High") or c_val),
                                    low=float(r.get("low") or r.get("Low") or c_val),
                                    close=float(c_val),
                                    volume=float(r.get("volume") or r.get("Volume") or 0.0),
                                    adjusted=adjusted,
                                )
                            )
                self._historical_last_status = "HEALTHY"
                self._historical_last_error = None
                self._historical_circuit_open_until = 0.0
                self._historical_consecutive_auth_errors = 0
                return bars
            except HistoricalRangeLimitError:
                raise
            except Exception as exc:
                exc_str = str(exc)
                exc_cls = exc.__class__.__name__

                # 1. Range limit failure (e.g. TimeFrameLimitFailed from gateway) - DO NOT open circuit breaker
                if "TimeFrameLimitFailed" in exc_str or "365 days" in exc_str:
                    logger.warning("Historical request for %s exceeded upstream timeframe limit: %s", sym, exc)
                    raise HistoricalRangeLimitError(f"Upstream timeframe limit exceeded for {sym}: {exc_str}") from exc

                # 2. Authentication failure (401 / invalid token) -> Open circuit breaker
                if "401" in exc_str or "invalid_token" in exc_str or "invalid_grant" in exc_str or "Unauthorized" in exc_str:
                    self._historical_consecutive_auth_errors += 1
                    self._historical_circuit_open_until = time.monotonic() + 60.0
                    self._historical_circuit_reason = CIRCUIT_REASON_AUTH
                    self._historical_last_status = "DEGRADED"
                    self._historical_last_error = f"Auth failure: {exc_str}"
                    logger.error("Historical authentication failure for %s. Circuit breaker OPEN for 60s: %s", sym, exc)
                    raise HistoricalAuthError(f"FiinQuant auth failure for {sym}: {exc_str}") from exc

                # 3. Entitlement failure (403 forbidden without TimeFrameLimitFailed)
                if "403" in exc_str or "Forbidden" in exc_str:
                    self._historical_last_status = "DEGRADED"
                    self._historical_last_error = f"Entitlement failure: {exc_str}"
                    logger.error("Historical entitlement failure for %s: %s", sym, exc)
                    raise HistoricalEntitlementError(f"FiinQuant entitlement failure for {sym}: {exc_str}") from exc

                # 4. Rate limit (429) -> Transient backoff
                if "429" in exc_str or "RateLimit" in exc_str:
                    self._historical_circuit_open_until = time.monotonic() + 10.0
                    self._historical_circuit_reason = CIRCUIT_REASON_RATE_LIMIT
                    logger.warning("Historical rate limit hit for %s. Backoff 10s: %s", sym, exc)
                    raise HistoricalRateLimitError(f"FiinQuant rate limit for {sym}: {exc_str}") from exc

                # 5. Upstream server error (500, 502, 503, 504, Timeout)
                if any(code in exc_str for code in ("500", "502", "503", "504", "timeout", "Timeout")):
                    self._historical_last_status = "DEGRADED"
                    self._historical_last_error = f"Upstream error: {exc_str}"
                    logger.warning("Historical upstream error for %s: %s", sym, exc)
                    raise HistoricalUpstreamError(f"FiinQuant upstream server error for {sym}: {exc_str}") from exc

                # 6. Transport / Network error
                self._historical_last_error = f"Transport error: {exc_cls}: {exc_str}"
                logger.warning("Historical transport error for %s: %s: %s", sym, exc_cls, exc_str)
                raise HistoricalTransportError(f"Transport error fetching {sym}: {exc_str}") from exc

        return await asyncio.to_thread(_fetch)

    async def get_stock_profiles(self, symbols: List[str]) -> List[Dict[str, Any]]:
        """Batch BasicInfor reads, cached per symbol for a day; no new streams."""
        symbols = sorted({s.strip().upper() for s in symbols if s.strip()})
        if not symbols:
            return []
        async with self._stock_profile_lock:
            missing = [s for s in symbols if s not in self._stock_profile_cache
                       or time.monotonic() - self._stock_profile_cache[s][0] >= 86400]
            if missing:
                if not self._session or not self._is_connected:
                    if not await self.connect():
                        raise RuntimeError("FiinQuant stock profiles are unavailable")

                def fetch():
                    value = self._session.BasicInfor(tickers=missing).get()
                    if hasattr(value, "get_data"):
                        value = value.get_data()
                    if hasattr(value, "to_dict"):
                        value = value.to_dict(orient="records")
                    if isinstance(value, dict):
                        value = [value]
                    return value if isinstance(value, list) else []

                records = await asyncio.to_thread(fetch)
                def clean(value):
                    return value.strip() if isinstance(value, str) and value.strip() else None

                by_symbol = {str(r.get("ticker", "")).strip().upper(): r
                             for r in records if isinstance(r, dict)}
                now = time.monotonic()
                for symbol in missing:
                    raw = by_symbol.get(symbol, {})
                    exchange = clean(raw.get("exchangeCode"))
                    self._stock_profile_cache[symbol] = (now, {
                        "symbol": symbol,
                        "name": clean(raw.get("organizationName")),
                        "short_name": clean(raw.get("organizationShortName")),
                        "exchange": exchange.upper() if exchange else None,
                    })
            return [dict(self._stock_profile_cache[s][1]) for s in symbols]

    async def get_market_overview(self, cw_symbols: List[str]) -> Dict[str, Any]:
        """Read the four index cards and HOSE volume leaders without new streams.

        This uses the documented ``realtime=False`` snapshot path and MarketBreadth, so
        the 33-symbol SignalR subscription budget remains exclusively available to the
        user's watchlist. Results are cached for 60 seconds in-session and five minutes
        outside the live session.
        """
        ttl = 60.0 if self._market_is_active() else 300.0
        if self._overview_cache and time.monotonic() - self._overview_cache_at < ttl:
            return self._overview_cache
        async with self._overview_lock:
            if self._overview_cache and time.monotonic() - self._overview_cache_at < ttl:
                return self._overview_cache
            if not self._session or not self._is_connected:
                if not await self.connect():
                    raise RuntimeError("FiinQuant market overview is unavailable")

            index_symbols = ["VN30", "VNINDEX", "VNFINLEAD", "VNDIAMOND"]

            def records(value: Any) -> List[Dict[str, Any]]:
                if value is None:
                    return []
                if hasattr(value, "get_data"):
                    value = value.get_data()
                if hasattr(value, "to_dict"):
                    try:
                        return value.to_dict(orient="records")
                    except TypeError:
                        value = value.to_dict()
                if isinstance(value, list):
                    return [dict(x) for x in value if isinstance(x, dict)]
                return [dict(value)] if isinstance(value, dict) else []

            def ticker_list(group: Optional[str] = None) -> List[str]:
                value = self._session.TickerList(ticker=group) if group else self._session.TickerList()
                if isinstance(value, str):
                    value = [value]
                try:
                    return sorted({str(x).strip().upper() for x in value if str(x).strip()})
                except TypeError:
                    return []

            def fetch_rows(tickers: List[str], *, by: str, period: int) -> List[Dict[str, Any]]:
                rows: List[Dict[str, Any]] = []
                for start in range(0, len(tickers), 100):
                    result = self._session.Fetch_Trading_Data(
                        realtime=False,
                        tickers=tickers[start:start + 100],
                        fields=["close", "volume", "value"],
                        adjusted=False,
                        by=by,
                        period=period,
                        lasted=True,
                    )
                    rows.extend(records(result))
                return rows

            def fetch_price_bands(tickers: List[str], session_date: str) -> List[Dict[str, Any]]:
                rows: List[Dict[str, Any]] = []
                for start in range(0, len(tickers), 100):
                    value = self._session.PriceStatistics().get_ceilingfloor(
                        tickers=tickers[start:start + 100],
                        from_date=session_date,
                        to_date=session_date,
                    )
                    rows.extend(records(value))
                return rows

            def build() -> Dict[str, Any]:
                captured = io.StringIO()
                with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
                    stocks = ticker_list("VNINDEX")
                    all_symbols = ticker_list()
                    listed_cws = [s for s in all_symbols if len(s) == 8 and s.startswith("C")]
                    # Current vendor ticker master is the broad source. The verified registry
                    # remains a truthful fallback for plans that do not expose CW master data.
                    clean_cws = listed_cws or sorted({s.strip().upper() for s in cw_symbols if s.strip()})
                    daily = fetch_rows(sorted(set(index_symbols + stocks + clean_cws)), by="1d", period=2)
                    intraday = fetch_rows(index_symbols, by="5m", period=48)
                    breadth = records(self._session.MarketBreadth().get(tickers=index_symbols))
                    daily_dates = [str(r.get("timestamp") or r.get("TradingDate") or "")[:10] for r in daily]
                    session_date = max((d for d in daily_dates if d), default="")
                    try:
                        bands = fetch_price_bands(stocks + clean_cws, session_date) if session_date else []
                    except Exception as exc:  # the ranking still works if this optional endpoint is not entitled
                        logger.warning("FiinQuant price bands unavailable for overview: %s", exc)
                        bands = []

                def key(row: Dict[str, Any]) -> str:
                    return str(row.get("ticker") or row.get("Ticker") or "").upper()
                def stamp(row: Dict[str, Any]) -> str:
                    return str(row.get("timestamp") or row.get("TradingDate") or row.get("tradingDate") or "")
                def num(row: Dict[str, Any], *names: str) -> Optional[float]:
                    for name in names:
                        value = row.get(name)
                        try:
                            return float(value) if value is not None else None
                        except (TypeError, ValueError):
                            pass
                    return None

                daily_by: Dict[str, List[Dict[str, Any]]] = {}
                for row in daily:
                    if key(row): daily_by.setdefault(key(row), []).append(row)
                intra_by: Dict[str, List[Dict[str, Any]]] = {}
                for row in intraday:
                    if key(row): intra_by.setdefault(key(row), []).append(row)
                breadth_by = {str(r.get("comGroupCode") or "").upper(): r for r in breadth}
                bands_by: Dict[str, Dict[str, Any]] = {}
                for row in bands:
                    symbol = key(row)
                    if symbol and (symbol not in bands_by or stamp(row) > stamp(bands_by[symbol])):
                        bands_by[symbol] = row

                indices = []
                for symbol in index_symbols:
                    bars = sorted(daily_by.get(symbol, []), key=stamp)
                    latest = bars[-1] if bars else {}
                    previous = bars[-2] if len(bars) > 1 else {}
                    intraday_bars = sorted(intra_by.get(symbol, []), key=stamp)
                    if intraday_bars:
                        latest_day = stamp(intraday_bars[-1])[:10]
                        intraday_bars = [x for x in intraday_bars if stamp(x)[:10] == latest_day]
                    current = intraday_bars[-1] if intraday_bars else latest
                    close, reference = num(current, "close", "Close"), num(previous, "close", "Close")
                    change = close - reference if close is not None and reference is not None else None
                    pct = change / reference * 100 if change is not None and reference else None
                    b = breadth_by.get(symbol, {})
                    indices.append({
                        "symbol": symbol, "value": close, "change": change, "change_percent": pct,
                        "volume": num(latest, "volume", "Volume"), "trading_value": num(latest, "value", "Value"),
                        "advancing": num(b, "totalStockUpPrice"), "ceiling": num(b, "totalStockOverCeiling"),
                        "unchanged": num(b, "totalStockNoChangePrice"), "declining": num(b, "totalStockDownPrice"),
                        "floor": num(b, "totalStockUnderFloor"), "as_of": stamp(current) or stamp(b),
                        "sparkline": [num(x, "close", "Close") for x in intraday_bars if num(x, "close", "Close") is not None],
                    })

                def leaders(universe: List[str]) -> List[Dict[str, Any]]:
                    out = []
                    for symbol in universe:
                        bars = sorted(daily_by.get(symbol, []), key=stamp)
                        if not bars: continue
                        row = bars[-1]; previous = bars[-2] if len(bars) > 1 else {}
                        volume = num(row, "volume", "Volume")
                        if volume is None: continue
                        price, reference = num(row, "close", "Close"), num(previous, "close", "Close")
                        band_row = bands_by.get(symbol, {})
                        ceiling = num(band_row, "ceilingValue")
                        floor = num(band_row, "floorValue")
                        def same(a: Optional[float], b: Optional[float]) -> bool:
                            return a is not None and b is not None and abs(a - b) < 1e-6
                        market_state = (
                            "CEILING" if same(price, ceiling) else
                            "FLOOR" if same(price, floor) else
                            "REFERENCE" if same(price, reference) else
                            "UP" if price is not None and reference is not None and price > reference else
                            "DOWN" if price is not None and reference is not None and price < reference else
                            "UNAVAILABLE"
                        )
                        out.append({
                            "symbol": symbol, "volume": volume, "price": price,
                            "reference": reference, "ceiling": ceiling, "floor": floor,
                            "market_state": market_state, "as_of": stamp(row),
                        })
                    return sorted(out, key=lambda x: x["volume"], reverse=True)[:5]

                as_of = max((x["as_of"] for x in indices if x["as_of"]), default=None)
                return {
                    "indices": indices,
                    "top_stock_volume": leaders(stocks),
                    "top_cw_volume": leaders(clean_cws),
                    "as_of": as_of,
                    "market_session_active": self._market_is_active(),
                    "stock_scope": "HOSE (VNINDEX constituents)",
                    "cw_scope": "HOSE covered warrants" if listed_cws else "verified active CW registry",
                    "source": "FIINQUANT",
                }

            try:
                result = await asyncio.to_thread(build)
            finally:
                self._tame_sdk_side_effects()
            self._overview_cache, self._overview_cache_at = result, time.monotonic()
            return result
