import logging
import asyncio
import threading
from typing import Iterator, List, Dict, Any, Optional, Callable, Set
from datetime import datetime, timedelta

from app.core.config import settings
from app.market_data.market_schemas import HistoricalBar
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
        if self._session is not None and self._is_connected:
            return True  # idempotent: already authenticated with a live session

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
        """Fully retire every stream this provider owns. Cancel-safe and time-bounded.

        Order matters: (1) synchronous hard teardown of each transport (stops the ping
        loop unconditionally, closes the socket, kills SDK reconnect, detaches the leaking
        log handler); (2) reap any ``ConnectionStateChecker`` the SDK left running,
        including from its internal reconnects; (3) best-effort SDK ``.stop()`` with a
        timeout (it may ``.join()`` threads); (4) a final reap.
        """
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
        """Undo FiinQuantX's global logging hijack after any stream operation.

        The SDK forces the root logger (and ``SignalRCoreClient``) to DEBUG and attaches a
        never-drained ``CustomHandler`` to root on every stream construction.
        """
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

            # _start_new_streams_sync stores the stream refs into ``self`` from inside the
            # worker thread, so a cancelled ``await`` here can never orphan a live stream.
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
            trade.start()
            self._trade_stream = trade
            self._owned_streams.append(trade)

            if ba_symbols:
                bidask = self._session.BidAsk(tickers=ba_symbols, callback=self._on_bidask_raw)
                bidask.start()
                self._bidask_stream = bidask
                self._owned_streams.append(bidask)

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
        }

    async def get_historical_bars(
        self,
        symbol: str,
        timeframe: str = "1D",
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        adjusted: bool = True,
    ) -> List[HistoricalBar]:
        """Fetches historical EOD bars via FiinQuant Fetch_Trading_Data."""
        if not self._session or not self._is_connected:
            connected = await self.connect()
            if not connected:
                return []

        sym = symbol.strip().upper()
        tf_norm = timeframe.strip().lower()
        if tf_norm in ("1d", "daily", "d"):
            by_param = "1d"
            default_days = 365
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
            default_days = 365

        default_from = (datetime.now() - timedelta(days=default_days)).strftime("%Y-%m-%d")
        f_date = from_date or default_from
        t_date = to_date or datetime.now().strftime("%Y-%m-%d")

        def _fetch():
            try:
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
                bars: List[HistoricalBar] = []

                if hasattr(df, "to_dict"):
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
                return bars
            except Exception as e:
                logger.error(f"Error fetching historical bars for {sym}: {e}")
                return []

        return await asyncio.to_thread(_fetch)
