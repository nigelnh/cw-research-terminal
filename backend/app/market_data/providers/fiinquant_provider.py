import logging
import asyncio
import copy
import threading
import time
import io
import contextlib
from importlib import metadata as importlib_metadata
from typing import Iterator, List, Dict, Any, Optional, Callable, Set
from datetime import date, datetime, timedelta, timezone

from app.core.config import settings
from app.market_data.feed_status import FeedAccess, MESSAGES, classify_provider_error, redact_provider_text
from app.market_data.providers.sdk_output import capture_sdk_output
from app.market_data.market_session import market_session
from app.market_data.trading_calendar import reference_session_date
from app.market_data.providers.fiinquant_normalization import normalize_event, number, first, timestamp
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
from app.market_data.providers.signalr_text_frame_adapter import (
    SignalRFrameError,
    SignalRFrameErrorKind,
    SignalRTextFrameAdapter,
)

logger = logging.getLogger(__name__)

# The signalrcore library (bundled with FiinQuantX) logs under this name, and the SDK's
# stream ctor forcibly re-enables DEBUG on it and on the root logger.
_SIGNALR_LOGGER_NAME = "SignalRCoreClient"
_NOISY_LOGGERS = (_SIGNALR_LOGGER_NAME, "signalrcore", "websocket", "websockets", "urllib3")
_SUPPORTED_SIGNALRCORE_VERSION = "0.9.71"


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

        self._access = FeedAccess()
        self._session: Any = None
        self._trade_stream: Any = None
        self._bidask_stream: Any = None
        self._active_symbols: List[str] = []
        self._event_callback: Optional[Callable[[str, Dict[str, Any], str], None]] = None
        self._status_callback: Optional[Callable[[], None]] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._is_connected = False
        self._upstream_status = "DISCONNECTED"
        self._last_error: Optional[str] = None

        # ---- Re-authentication floor ----
        # The 20s snapshot poll, set_subscriptions and the reconnect worker each call
        # connect() when they notice a dropped session. The account permits ONE concurrent
        # connection, so every fresh login() evicts the live SignalR streams the previous
        # token owned. This paces unsolicited re-auth; a session the SDK reports explicitly
        # invalid (is_login False) still re-authenticates immediately.
        self._reauth_min_interval_seconds = float(
            settings.FIINQUANT_REAUTH_MIN_INTERVAL_SECONDS
        )
        self._last_auth_attempt_monotonic: float = float("-inf")
        # A stream that will not start on a nominally-valid session is the real "session is
        # dead" signal (a REST endpoint answering 401 is not). After this many consecutive
        # failed restarts the reconnect worker re-authenticates once, still subject to the
        # floor above. `_force_reauth` is a narrow intent flag read only by the reconnect
        # path - it does not disturb `_is_connected`, which stays owned by real login
        # success/failure and disconnect.
        self._consecutive_stream_start_failures = 0
        self._stream_failures_before_reauth = int(
            settings.FIINQUANT_STREAM_FAILURES_BEFORE_REAUTH
        )
        self._force_reauth = False

        # ---- SignalR lifecycle ownership ----
        self._lifecycle_lock = asyncio.Lock()
        self._generation = 0
        # Authentication generation is intentionally stable while an authenticated
        # session is reused. Stream generation changes for every replacement so late
        # callbacks from a retired hub cannot restart the current healthy lifecycle.
        self._stream_generation = 0
        self._shutting_down = False
        self._owned_streams: List[Any] = []          # the SDK stream objects we currently own
        self._connect_count = 0
        self._disconnect_count = 0
        self._stream_restart_count = 0
        self._orphans_reaped = 0
        self._reconnect_count = 0

        # ---- SignalR application-frame adapter & feed observability ----
        self._signalr_adapters: Dict[int, SignalRTextFrameAdapter] = {}
        self._signalr_timeout_timers: Dict[int, threading.Timer] = {}
        self._failed_signalr_streams: Set[int] = set()
        self._signalr_metrics_lock = threading.RLock()
        self._signalr_adapter_installed_count = 0
        self._signalr_frame_error_count = 0
        self._signalr_decode_error_count = 0
        self._signalr_partial_timeout_count = 0
        self._signalr_buffer_overflow_count = 0
        self._last_signalr_frame_error_kind: Optional[str] = None
        self._last_signalr_frame_error_at_ms: Optional[int] = None
        self._last_trade_tick_at_ms: Optional[int] = None
        self._last_book_tick_at_ms: Optional[int] = None
        # Per-lifecycle channel timestamps are reset every time streams are replaced.
        # The lifetime timestamps above remain useful for observability, but cannot be
        # used to declare a freshly-created channel healthy.
        self._current_trade_tick_at_ms: Optional[int] = None
        self._current_book_tick_at_ms: Optional[int] = None
        self._current_stream_last_tick_at_ms: Optional[int] = None
        self._current_stream_started_at_monotonic: Optional[float] = None
        self._current_stream_requires_book = False
        self._feed_live_notified = False
        self._feed_freshness_seconds = float(settings.FIINQUANT_FEED_FRESHNESS_SECONDS)

        # ---- Stream-liveness watchdog ----
        # FiinQuant can stop pushing frames without ever firing on_close, so the SDK still
        # reports `connected` and no reconnect is ever scheduled. `get_health()` computes
        # STALE for exactly this case, but it is pull-based - nothing acted on it, and a
        # session could sit silent for the rest of the day (observed 2026-09-07: last tick
        # 09:41 ICT, still "connected" at 10:51 with reconnect_count 0).
        self._stream_watchdog_task: Optional[asyncio.Task] = None
        self._stream_silence_reconnect_seconds = float(
            settings.FIINQUANT_STREAM_SILENCE_RECONNECT_SECONDS
        )
        self._stream_watchdog_interval_seconds = float(
            settings.FIINQUANT_STREAM_WATCHDOG_INTERVAL_SECONDS
        )
        self._silent_stream_reconnect_count = 0
        # Progressive backoff for a stream that stays silent through repeated forced
        # reconnects. Without it the watchdog tears down and rebuilds a genuinely-dead feed
        # (expired entitlement, provider outage) every FIINQUANT_STREAM_SILENCE_RECONNECT_
        # SECONDS for the whole session. The enforced silence budget doubles per silent
        # forced reconnect, capped, and snaps back to the base the moment any tick arrives.
        self._silent_watchdog_escalation = 0
        self._watchdog_silence_budget_cap_seconds = float(
            settings.FIINQUANT_STREAM_SILENCE_BUDGET_CAP_SECONDS
        )
        self._watchdog_last_seen_tick_at_ms: Optional[int] = None

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
        self._seconds_to_display_rollover: Callable[[], float] = (
            market_session.seconds_until_display_rollover
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
        # Index breadth is computed from ~430 constituents (MarketBreadth is not licensed);
        # the SDK issues one HTTP request per ticker, so it is refreshed on its own slow
        # cadence in the background and never blocks the overview payload.
        self._breadth_cache: Dict[str, Dict[str, int]] = {}
        self._stock_leaders_cache: List[Dict[str, Any]] = []
        self._breadth_cache_at: float = 0.0
        self._breadth_task: Optional[asyncio.Task] = None
        self._stock_profile_lock = asyncio.Lock()
        self._stock_profile_cache: Dict[str, tuple[float, Dict[str, Any]]] = {}
        # Fundamentals. Valuation moves once a day, statements once a quarter, so both
        # are cached hard - this is a request/response read that must never compete with
        # the realtime streams for the account's attention.
        self._fundamentals_lock = asyncio.Lock()
        self._valuation_cache: Dict[str, tuple[float, Dict[str, Any]]] = {}
        self._ratios_cache: Dict[str, tuple[float, List[Dict[str, Any]]]] = {}
        self._reference_lock = asyncio.Lock()

    def _sdk_call(self, scope, fn, *args):
        blocked = self._access.blocked(scope)
        if blocked:
            error = HistoricalAuthError if blocked == "AUTH_REQUIRED" else HistoricalEntitlementError if blocked in ("ENTITLEMENT_EXPIRED", "DATASET_FORBIDDEN") else HistoricalRateLimitError if blocked == "RATE_LIMITED" else HistoricalUpstreamError
            raise error(f"{blocked}: {MESSAGES[blocked]}")
        try:
            with capture_sdk_output() as output:
                result = fn(*args)
            code = classify_provider_error(output.getvalue())
            if code:
                error = HistoricalAuthError if code == "AUTH_REQUIRED" else HistoricalEntitlementError if code in ("ENTITLEMENT_EXPIRED", "DATASET_FORBIDDEN") else HistoricalRateLimitError if code == "RATE_LIMITED" else HistoricalUpstreamError
                raise error(f"{code}: {MESSAGES[code]}")
            if result is not None and (not isinstance(result, (list, dict)) or len(result) > 0):
                self._access.success(scope)
            return result
        except Exception as exc:
            code = self._access.record(scope, exc)
            # Only a failure of the login call itself (scope "authentication") takes the
            # whole connection down. A REST endpoint answering 401 - get_ceilingfloor does
            # by account design, and a snapshot poll can race a token refresh - must not
            # clear _is_connected: every path that calls connect() re-reads it, so one
            # endpoint's 401 was minting a fresh login on the very next poll (~3x/min in
            # production), and on a one-connection account each login evicts the SignalR
            # streams. Same rule as feed_status' scope isolation - a rejection stays in the
            # scope that produced it.
            if code == "AUTH_REQUIRED" and scope == "authentication":
                self._is_connected = False
            self._notify_status_change()
            if code:
                error = HistoricalAuthError if code == "AUTH_REQUIRED" else HistoricalEntitlementError if code in ("ENTITLEMENT_EXPIRED", "DATASET_FORBIDDEN") else HistoricalRateLimitError if code == "RATE_LIMITED" else HistoricalUpstreamError
                raise error(f"{code}: {MESSAGES[code]}") from None
            raise

    def set_event_callback(self, callback: Callable[[str, Dict[str, Any], str], None]) -> None:
        self._event_callback = callback
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None

    def set_status_callback(self, callback: Callable[[], None]) -> None:
        """Register a loop-safe observer for upstream state transitions."""

        self._status_callback = callback

    def _notify_status_change(self) -> None:
        callback = self._status_callback
        if callback is None:
            return
        self._ensure_loop()
        loop = self._loop
        if loop is None or not loop.is_running():
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            callback()
        else:
            loop.call_soon_threadsafe(callback)

    def _ensure_loop(self) -> None:
        if self._loop is None or self._loop.is_closed():
            try:
                self._loop = asyncio.get_running_loop()
            except RuntimeError:
                pass

    def _maybe_notify_feed_live(self, now_ms: int) -> bool:
        """Notify once when all required current-stream channels first become fresh."""

        if (
            self._feed_live_notified
            or not self._is_connected
            or self._upstream_status != "CONNECTED"
        ):
            return False
        try:
            session_active = bool(self._market_is_active())
        except Exception:  # noqa: BLE001 - a calendar failure must not break callbacks
            session_active = False
        if not session_active:
            return False

        trade_connected = bool(
            self._trade_stream is not None
            and getattr(self._trade_stream, "connected", False)
        )
        book_connected = bool(
            self._bidask_stream is not None
            and getattr(self._bidask_stream, "connected", False)
        )

        def _fresh(value: Optional[int]) -> bool:
            return bool(
                value is not None
                and max(0.0, (now_ms - value) / 1000.0)
                <= self._feed_freshness_seconds
            )

        is_live = bool(
            trade_connected
            and _fresh(self._current_trade_tick_at_ms)
            and (
                not self._current_stream_requires_book
                or (book_connected and _fresh(self._current_book_tick_at_ms))
            )
        )
        if is_live:
            with self._signalr_metrics_lock:
                if self._feed_live_notified:
                    return False
                self._feed_live_notified = True
            self._notify_status_change()
            return True
        return False

    def _on_trade_raw(
        self,
        data: Any,
        stream_generation: Optional[int] = None,
    ) -> None:
        """Callback invoked by FiinQuant SDK Trading_Data_Stream on worker thread."""
        if stream_generation is not None and (
            self._shutting_down or stream_generation != self._stream_generation
        ):
            return
        try:
            d = data.to_dict() if hasattr(data, "to_dict") else (data if isinstance(data, dict) else vars(data))
            d = normalize_event(d)
            sym = str(d.get("Ticker", "")).upper()
            if not sym:
                return
            tick_ms = int(time.time() * 1000)
            self._last_trade_tick_at_ms = tick_ms
            self._current_trade_tick_at_ms = tick_ms
            self._current_stream_last_tick_at_ms = tick_ms
            self._ensure_loop()
            if self._loop and self._loop.is_running() and self._event_callback:
                self._loop.call_soon_threadsafe(self._event_callback, "trade", d, sym)
            self._maybe_notify_feed_live(tick_ms)
        except Exception as err:
            logger.warning(f"Error handling raw trade event: {err}")

    def _on_bidask_raw(
        self,
        data: Any,
        stream_generation: Optional[int] = None,
    ) -> None:
        """Callback invoked by FiinQuant SDK BidAsk stream on worker thread."""
        if stream_generation is not None and (
            self._shutting_down or stream_generation != self._stream_generation
        ):
            return
        try:
            d = data.to_dict() if hasattr(data, "to_dict") else (data if isinstance(data, dict) else vars(data))
            d = normalize_event(d)
            sym = str(d.get("Ticker", "")).upper()
            if not sym:
                return
            tick_ms = int(time.time() * 1000)
            self._last_book_tick_at_ms = tick_ms
            self._current_book_tick_at_ms = tick_ms
            self._current_stream_last_tick_at_ms = tick_ms
            self._ensure_loop()
            if self._loop and self._loop.is_running() and self._event_callback:
                self._loop.call_soon_threadsafe(self._event_callback, "bidask", d, sym)
            self._maybe_notify_feed_live(tick_ms)
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
        if (
            self._session is not None
            and getattr(self._session, "is_login", False)
            and self._is_connected
            and not self._force_reauth
        ):
            return True  # idempotent: already authenticated with a live valid session

        # Re-auth floor. Unless the SDK reports this session explicitly invalid, do not mint
        # a new token more often than _reauth_min_interval_seconds: a burst of callers each
        # asking to reconnect otherwise logs in several times in seconds, and each new token
        # drops the SignalR streams the previous one owns.
        session_explicitly_invalid = (
            self._session is not None and not getattr(self._session, "is_login", False)
        )
        if not session_explicitly_invalid:
            since_last = time.monotonic() - self._last_auth_attempt_monotonic
            if since_last < self._reauth_min_interval_seconds:
                logger.debug(
                    "FiinQuant re-auth suppressed: %.0fs since last attempt (floor %.0fs).",
                    since_last, self._reauth_min_interval_seconds,
                )
                return False
        self._last_auth_attempt_monotonic = time.monotonic()

        self._ensure_loop()
        session = await asyncio.to_thread(self._sdk_call, "authentication", self._create_session)
        self._tame_sdk_side_effects()

        if session is not None:
            self._session = session
            self._access.inspect_session(session)
            self._is_connected = True
            self._force_reauth = False
            self._consecutive_stream_start_failures = 0
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
            if self._stream_watchdog_task is not None and not self._stream_watchdog_task.done():
                self._stream_watchdog_task.cancel()
                self._stream_watchdog_task = None
            if self._breadth_task is not None and not self._breadth_task.done():
                self._breadth_task.cancel()
                self._breadth_task = None
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
        # Invalidate callbacks before touching transports: hard-stop/SDK teardown can
        # synchronously invoke callbacks registered on the retiring hubs.
        self._stream_generation += 1
        with self._signalr_metrics_lock:
            self._feed_live_notified = False
        streams = list(self._owned_streams)
        self._owned_streams.clear()

        try:
            for s in streams:
                self._release_signalr_frame_adapter(s)
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

    @staticmethod
    def _signalrcore_version() -> Optional[str]:
        try:
            return importlib_metadata.version("signalrcore")
        except importlib_metadata.PackageNotFoundError:
            return None

    def _release_signalr_frame_adapter(self, stream: Any) -> None:
        key = id(stream)
        with self._signalr_metrics_lock:
            timer = self._signalr_timeout_timers.pop(key, None)
            adapter = self._signalr_adapters.pop(key, None)
            self._failed_signalr_streams.discard(key)
        if timer is not None:
            timer.cancel()
        if adapter is not None:
            adapter.discard_partial()

    def _arm_signalr_partial_timeout(
        self,
        stream: Any,
        adapter: SignalRTextFrameAdapter,
    ) -> None:
        """Keep exactly one timer for the adapter's current payload-free deadline."""

        key = id(stream)
        deadline = adapter.partial_deadline
        with self._signalr_metrics_lock:
            previous = self._signalr_timeout_timers.pop(key, None)
        if previous is not None:
            previous.cancel()
        if deadline is None:
            return

        delay = max(0.0, deadline - time.monotonic())

        def _expire() -> None:
            adapter.expire_partial()
            with self._signalr_metrics_lock:
                if self._signalr_timeout_timers.get(key) is timer:
                    self._signalr_timeout_timers.pop(key, None)

        timer = threading.Timer(delay, _expire)
        timer.daemon = True
        with self._signalr_metrics_lock:
            self._signalr_timeout_timers[key] = timer
        timer.start()

    def _on_signalr_frame_error(
        self,
        stream: Any,
        stream_generation: int,
        channel: str,
        error: SignalRFrameError,
    ) -> None:
        """Reject one malformed/expired batch and hand recovery to our reconnect loop."""

        if (
            self._shutting_down
            or stream_generation != self._stream_generation
            or not self._active_symbols
        ):
            return

        key = id(stream)
        with self._signalr_metrics_lock:
            if key in self._failed_signalr_streams:
                return
            self._failed_signalr_streams.add(key)
            self._signalr_frame_error_count += 1
            if error.kind is SignalRFrameErrorKind.FRAME_ERROR:
                self._signalr_decode_error_count += 1
            elif error.kind is SignalRFrameErrorKind.PARTIAL_TIMEOUT:
                self._signalr_partial_timeout_count += 1
            elif error.kind is SignalRFrameErrorKind.BUFFER_OVERFLOW:
                self._signalr_buffer_overflow_count += 1
            self._last_signalr_frame_error_kind = error.kind.value
            self._last_signalr_frame_error_at_ms = int(time.time() * 1000)
            counter = self._signalr_frame_error_count

        # Payload contents and exception messages are intentionally excluded.
        logger.warning(
            "SignalR frame rejected channel=%s kind=%s buffered_bytes=%d "
            "incoming_bytes=%d counter=%d",
            channel,
            error.kind.value,
            error.buffered_bytes,
            error.incoming_bytes,
            counter,
        )
        self._last_error = f"SignalR {error.kind.value}"
        self._upstream_status = "RESTARTING"
        self._notify_status_change()
        self._hard_stop_stream_sync(stream)

        # Let synchronous startup unwind before recovery. Recheck the generation when
        # the delayed callback runs so a replacement cannot inherit this request.
        self._ensure_loop()
        loop = self._loop
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(
                lambda: loop.call_later(
                    0.05,
                    self._schedule_reconnect,
                    stream_generation,
                )
            )

    def _attach_signalr_frame_adapter(
        self,
        stream: Any,
        hub: Any,
        stream_generation: int,
        channel: str,
    ) -> bool:
        """Attach to a hub returned by the SDK before ``hub.start()`` runs."""

        transport = getattr(hub, "transport", None) if hub is not None else None
        original = getattr(transport, "on_message", None) if transport is not None else None
        if transport is None or not callable(original):
            logger.warning("SignalR frame adapter skipped: transport shape is unsupported.")
            return False

        # A FiinQuant stream may rebuild its hub internally. Retire the prior adapter
        # before replacing it so no timeout timer survives on the superseded transport.
        self._release_signalr_frame_adapter(stream)

        adapter = SignalRTextFrameAdapter(
            original,
            on_error=lambda error: self._on_signalr_frame_error(
                stream, stream_generation, channel, error
            ),
        )

        def _buffered_on_message(app: Any, raw_message: str) -> Any:
            if self._shutting_down or stream_generation != self._stream_generation:
                return None
            result = adapter.on_message(app, raw_message)
            self._arm_signalr_partial_timeout(stream, adapter)
            return result

        transport.on_message = _buffered_on_message
        with self._signalr_metrics_lock:
            self._signalr_adapters[id(stream)] = adapter
            self._signalr_adapter_installed_count += 1

        # Apply the same lifecycle guard here because FiinQuant builds the hub inside a
        # background thread and calls hub.start() immediately afterwards.
        if hasattr(transport, "reconnection_handler"):
            transport.reconnection_handler = None
        if (
            callable(getattr(hub, "on_close", None))
            and not getattr(hub, "_cw_close_guard_installed", False)
        ):
            hub.on_close(
                lambda: self._on_stream_closed_callback(stream_generation)
            )
            setattr(hub, "_cw_close_guard_installed", True)
        return True

    def _install_signalr_frame_adapter(
        self,
        stream: Any,
        stream_generation: int,
        channel: str,
    ) -> bool:
        """Guard and wrap FiinQuant's lazy hub builder for signalrcore 0.9.71."""

        version = self._signalrcore_version()
        if version != _SUPPORTED_SIGNALRCORE_VERSION:
            logger.warning(
                "SignalR frame adapter disabled for unsupported signalrcore version=%s",
                version or "missing",
            )
            return False

        hub = getattr(stream, "hub_connection", None)
        if hub is not None:
            return self._attach_signalr_frame_adapter(
                stream, hub, stream_generation, channel
            )

        build_connection = getattr(stream, "_build_connection", None)
        if not callable(build_connection):
            logger.debug("SignalR frame adapter skipped: lazy hub builder is unavailable.")
            return False
        if getattr(stream, "_cw_signalr_build_wrapped", False):
            return True

        def _guarded_build_connection() -> Any:
            built_hub = build_connection()
            self._attach_signalr_frame_adapter(
                stream, built_hub, stream_generation, channel
            )
            return built_hub

        stream._build_connection = _guarded_build_connection
        setattr(stream, "_cw_signalr_build_wrapped", True)
        return True

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

    def _disable_sdk_reconnect_guarded(
        self,
        stream: Any,
        stream_generation: int,
    ) -> None:
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
            if (
                hub is not None
                and callable(getattr(hub, "on_close", None))
                and not getattr(hub, "_cw_close_guard_installed", False)
            ):
                try:
                    hub.on_close(
                        lambda: self._on_stream_closed_callback(stream_generation)
                    )
                    setattr(hub, "_cw_close_guard_installed", True)
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

    def _on_stream_closed_callback(self, stream_generation: int) -> None:
        """Callback invoked on worker thread when SignalR transport drops."""
        if (
            self._shutting_down
            or stream_generation != self._stream_generation
            or not self._active_symbols
        ):
            return
        self._upstream_status = "RESTARTING"
        self._notify_status_change()
        self._ensure_loop()
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(
                self._schedule_reconnect,
                stream_generation,
            )

    def _schedule_reconnect(self, stream_generation: Optional[int] = None) -> None:
        if (
            self._shutting_down
            or not self._active_symbols
            or (
                stream_generation is not None
                and stream_generation != self._stream_generation
            )
        ):
            return
        if self._reconnect_task is not None and not self._reconnect_task.done():
            return
        self._ensure_loop()
        if self._loop and self._loop.is_running():
            self._reconnect_task = self._loop.create_task(self._reconnect_worker())

    # ------------------------------------------------------------------ #
    # Stream-liveness watchdog
    # ------------------------------------------------------------------ #
    def _ensure_stream_watchdog(self) -> None:
        """Start the watchdog if it is not already running. Idempotent."""
        if self._stream_silence_reconnect_seconds <= 0 or self._shutting_down:
            return
        if self._stream_watchdog_task is not None and not self._stream_watchdog_task.done():
            return
        self._ensure_loop()
        if self._loop and self._loop.is_running():
            self._stream_watchdog_task = self._loop.create_task(self._stream_watchdog())

    def _silent_stream_age_seconds(self) -> Optional[float]:
        """Seconds since the CURRENT stream last delivered any frame, or None when a
        silence judgement would be unsound (no stream, off-session, still warming up).

        Deliberately uses `_current_stream_last_tick_at_ms` - any frame on either channel
        counts as life. A book-only or trade-only lull is normal; total silence is not.
        """
        if self._shutting_down or not self._active_symbols or not self._is_connected:
            return None
        # Never judge silence outside a session: FiinQuant legitimately stops pushing at
        # lunch, pre-open and post-close, and `_compute_reconnect_delay` already paces that.
        try:
            if not self._market_is_active():
                return None
        except Exception:  # noqa: BLE001 - a calendar fault must not trigger reconnect storms
            return None
        # A reconnect is already in flight - let it finish rather than stacking another.
        if self._upstream_status == "RESTARTING":
            return None
        if self._reconnect_task is not None and not self._reconnect_task.done():
            return None
        started = self._current_stream_started_at_monotonic
        if started is None:
            return None
        # Give a fresh stream the full silence budget to produce its first frame, so a
        # slow start is never mistaken for a dead feed.
        stream_age = max(0.0, time.monotonic() - started)
        if stream_age < self._stream_silence_reconnect_seconds:
            return None
        last = self._current_stream_last_tick_at_ms
        if last is None:
            # Connected for longer than the budget and never delivered anything.
            return stream_age
        return max(0.0, (time.time() * 1000 - last) / 1000.0)

    def _watchdog_effective_silence_budget(self) -> float:
        """The silence the watchdog currently tolerates before forcing a reconnect.

        Starts at ``_stream_silence_reconnect_seconds`` and doubles after each forced
        reconnect that still produced no tick, capped at
        ``_watchdog_silence_budget_cap_seconds``. A feed that is genuinely gone (expired
        entitlement, provider-side outage) is then re-probed on a widening interval instead
        of every 90s for the whole session - each probe being a full stream teardown and
        rebuild against a one-connection account. ``_stream_watchdog`` resets the escalation
        to zero the moment any tick arrives.
        """
        base = self._stream_silence_reconnect_seconds
        if self._silent_watchdog_escalation <= 0:
            return base
        widened = base * (2 ** self._silent_watchdog_escalation)
        return min(widened, self._watchdog_silence_budget_cap_seconds)

    async def _stream_watchdog(self) -> None:
        """Force a reconnect when a 'connected' stream has gone silent mid-session.

        This is the only component that converts silence into a reconnect; it reuses
        `_schedule_reconnect`, which is single-flighted, so the provider keeps exactly one
        reconnect owner.
        """
        interval = max(1.0, self._stream_watchdog_interval_seconds)
        try:
            while not self._shutting_down:
                await asyncio.sleep(interval)
                if self._shutting_down:
                    return
                # Nothing left to watch: exit rather than linger. A later stream start
                # re-arms via `_ensure_stream_watchdog`, which is idempotent.
                if not self._owned_streams and not self._active_symbols:
                    return
                # A tick since the last sample means the feed is alive again: clear the
                # escalation so the next lull is judged against the base budget.
                last_tick = self._current_stream_last_tick_at_ms
                if last_tick is not None and last_tick != self._watchdog_last_seen_tick_at_ms:
                    if self._silent_watchdog_escalation:
                        logger.info(
                            "FiinQuant feed delivered a tick - resetting watchdog escalation "
                            "(was %d).",
                            self._silent_watchdog_escalation,
                        )
                    self._silent_watchdog_escalation = 0
                self._watchdog_last_seen_tick_at_ms = last_tick

                try:
                    age = self._silent_stream_age_seconds()
                except Exception as err:  # noqa: BLE001 - the watchdog must never die
                    logger.warning("Stream watchdog check failed: %s", err)
                    continue
                budget = self._watchdog_effective_silence_budget()
                if age is None or age < budget:
                    continue
                self._silent_stream_reconnect_count += 1
                self._silent_watchdog_escalation += 1
                logger.warning(
                    "FiinQuant stream silent for %.0fs (budget %.0fs) during an active session "
                    "while still reporting connected - forcing reconnect (generation %d, silent "
                    "restarts %d, escalation %d).",
                    age, budget, self._stream_generation,
                    self._silent_stream_reconnect_count, self._silent_watchdog_escalation,
                )
                # Reset the backoff: this is a fresh failure mode, not a retry of a
                # connection that has been failing repeatedly.
                self._reconnect_backoff_index = 0
                self._schedule_reconnect()
        except asyncio.CancelledError:
            raise

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
            # The OPEN is the right bound here, not the 08:00 data rollover: this paces a
            # stream reconnect, and there is nothing to receive until trading resumes.
            secs_to_open = max(0.0, float(self._seconds_to_next_session()))
        except Exception:  # noqa: BLE001 - never let a calendar bug wedge reconnect
            return base
        return max(base, min(self._off_session_reconnect_seconds, secs_to_open))

    async def _reconnect_worker(self) -> None:
        """Single-flighted, bounded-backoff reconnect loop owned exclusively by FiinQuantProvider."""
        current_task = asyncio.current_task()
        try:
            while not self._shutting_down and self._active_symbols:
                delay = max(self._compute_reconnect_delay(), self._access.retry_after("stream"))
                try:
                    session_active = self._market_is_active()
                except Exception:  # noqa: BLE001 - health logging must not wedge recovery
                    session_active = False
                logger.info(
                    "SignalR stream disconnected. Scheduling provider reconnect in %.1fs "
                    "(generation %d, session_active=%s)...",
                    delay, self._generation, session_active,
                )
                await asyncio.sleep(delay)

                retry = False
                async with self._lifecycle_lock:
                    if self._shutting_down or not self._active_symbols:
                        return

                    self._upstream_status = "RESTARTING"
                    self._notify_status_change()
                    await self._retire_streams_locked()

                    # Reuse an authenticated session. Re-authenticate only after it expires
                    # or after repeated stream-start failures asked us to (`_force_reauth`).
                    is_valid_session = (
                        self._session is not None
                        and self._is_connected
                        and getattr(self._session, "is_login", False)
                        and not self._force_reauth
                    )
                    if not is_valid_session:
                        logger.info(
                            "FiinQuant session invalid/expired. Re-authenticating for reconnect..."
                        )
                        if not await self._connect_locked():
                            self._reconnect_backoff_index += 1
                            self._upstream_status = "ERROR"
                            self._notify_status_change()
                            retry = True

                    if not retry:
                        gen = self._generation
                        stream_gen = self._stream_generation
                        self._stream_restart_count += 1
                        self._reconnect_count += 1
                        err = await asyncio.to_thread(
                            self._start_new_streams_sync,
                            self._active_symbols,
                            stream_gen,
                        )
                        self._tame_sdk_side_effects()

                        if not self._owned_streams or err:
                            self._reconnect_backoff_index += 1
                            self._consecutive_stream_start_failures += 1
                            self._upstream_status = "ERROR"
                            self._last_error = err
                            logger.error(
                                "SignalR stream reconnect attempt failed (%d in a row): %s",
                                self._consecutive_stream_start_failures, err,
                            )
                            # A stream that will not start on a session the SDK still calls
                            # valid is the real "the token is dead" signal. Ask the next pass
                            # to re-authenticate; the floor in _connect_locked keeps that
                            # from becoming a login storm during a real outage.
                            if (
                                not self._force_reauth
                                and self._consecutive_stream_start_failures
                                >= self._stream_failures_before_reauth
                            ):
                                logger.warning(
                                    "%d consecutive stream restarts failed on a nominally "
                                    "valid session - re-authenticating on the next attempt.",
                                    self._consecutive_stream_start_failures,
                                )
                                self._force_reauth = True
                            self._notify_status_change()
                            retry = True
                        else:
                            self._reconnect_backoff_index = 0
                            self._consecutive_stream_start_failures = 0
                            self._upstream_status = "CONNECTED"
                            self._last_error = None
                            logger.info(
                                "SignalR stream reconnect successful for %d symbols "
                                "(generation %d).",
                                len(self._active_symbols), gen,
                            )
                            if not self._maybe_notify_feed_live(
                                int(time.time() * 1000)
                            ):
                                self._notify_status_change()

                if not retry:
                    return
                # Stay inside this single task for the next bounded-backoff attempt.
                # Calling _schedule_reconnect here would be ignored because this task
                # is still running, permanently wedging recovery after one failure.
        finally:
            if self._reconnect_task is current_task:
                self._reconnect_task = None

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
            stream_gen = self._stream_generation

            # Publish the target before stream.start(): signalrcore may invoke an
            # on_close/on_error callback synchronously from start(). Those callbacks
            # must see a reconnectable target instead of dropping the recovery request
            # because the prior lifecycle left _active_symbols empty.
            self._active_symbols = clean_symbols

            err = await asyncio.to_thread(
                self._start_new_streams_sync,
                clean_symbols,
                stream_gen,
            )
            self._last_error = err
            self._tame_sdk_side_effects()

            if not self._owned_streams:
                self._upstream_status = "ERROR"
                logger.error("FiinQuant stream startup failed (generation %d): %s", gen, err)
                self._schedule_reconnect()
                return False

            self._upstream_status = "CONNECTED"
            # A deliberate (re)subscription is a clean slate: clear the silent-feed
            # escalation and the failed-restart streak so the watchdog and the reconnect
            # worker start from the base cadence again.
            self._silent_watchdog_escalation = 0
            self._watchdog_last_seen_tick_at_ms = None
            self._consecutive_stream_start_failures = 0
            self._force_reauth = False
            logger.info(
                "FiinQuant streams active for %d symbols (generation %d): %s",
                len(clean_symbols), gen, clean_symbols,
            )
            # A live stream is the only thing worth watching for silence.
            self._ensure_stream_watchdog()
            self._maybe_notify_feed_live(int(time.time() * 1000))
            return True

    def _start_new_streams_sync(self, symbols, stream_generation):
        denied = self._access.blocked("stream")
        if denied:
            return MESSAGES[denied]
        with capture_sdk_output() as output:
            error = self._start_new_streams_impl(symbols, stream_generation)
        code = self._access.record("stream", output.getvalue() or error or "")
        return MESSAGES[code] if code else redact_provider_text(error) if error else None

    def _start_new_streams_impl(
        self,
        clean_symbols: List[str],
        stream_generation: int,
    ) -> Optional[str]:
        """Runs in a worker thread. Stores stream refs into ``self`` IMMEDIATELY."""
        trade: Any = None
        bidask: Any = None
        try:
            self._current_trade_tick_at_ms = None
            self._current_book_tick_at_ms = None
            self._current_stream_last_tick_at_ms = None
            self._current_stream_started_at_monotonic = time.monotonic()
            ba_symbols = [s for s in clean_symbols if s not in ("VNINDEX", "VN30", "HNXINDEX", "UPCOM")]
            self._current_stream_requires_book = bool(ba_symbols)

            trade = self._session.Trading_Data_Stream(
                tickers=clean_symbols,
                callback=lambda data: self._on_trade_raw(data, stream_generation),
            )
            if hasattr(trade, "_handle_disconnect"):
                try:
                    setattr(trade, "_handle_disconnect", lambda: None)
                except Exception:
                    pass
            self._install_signalr_frame_adapter(
                trade,
                stream_generation,
                "trade",
            )
            trade.start()
            self._trade_stream = trade
            self._owned_streams.append(trade)

            if ba_symbols:
                bidask = self._session.BidAsk(
                    tickers=ba_symbols,
                    callback=lambda data: self._on_bidask_raw(data, stream_generation),
                )
                if hasattr(bidask, "_handle_disconnect"):
                    try:
                        setattr(bidask, "_handle_disconnect", lambda: None)
                    except Exception:
                        pass
                self._install_signalr_frame_adapter(
                    bidask,
                    stream_generation,
                    "book",
                )
                bidask.start()
                self._bidask_stream = bidask
                self._owned_streams.append(bidask)

            # Proactively disable broken SDK / signalrcore competing reconnect paths with compatibility guards
            for s in [trade, self._bidask_stream]:
                if s is not None:
                    self._disable_sdk_reconnect_guarded(s, stream_generation)

            return None
        except Exception as e:  # noqa: BLE001
            err = f"{e.__class__.__name__}: {e}"
            for failed_stream in (trade, bidask):
                if failed_stream is None:
                    continue
                self._release_signalr_frame_adapter(failed_stream)
                self._hard_stop_stream_sync(failed_stream)
                try:
                    failed_stream.stop()
                except Exception:  # noqa: BLE001 - startup is already failing
                    pass
            self._owned_streams.clear()
            self._trade_stream = None
            self._bidask_stream = None
            logger.error("Failed to start FiinQuant streams for %s: %s", clean_symbols, err)
            return err

    def get_active_subscriptions(self) -> List[str]:
        return list(self._active_symbols)

    def get_health(self) -> Dict[str, Any]:
        trade_conn = getattr(self._trade_stream, "connected", False) if self._trade_stream else False
        ba_conn = getattr(self._bidask_stream, "connected", False) if self._bidask_stream else False
        stream_connected = bool(trade_conn or ba_conn)
        required_channels_connected = bool(
            trade_conn and (not self._current_stream_requires_book or ba_conn)
        )
        session_active = bool(self._market_is_active())
        now_ms = int(time.time() * 1000)
        current_tick = self._current_stream_last_tick_at_ms

        def _tick_age(value: Optional[int]) -> Optional[float]:
            return max(0.0, (now_ms - value) / 1000.0) if value is not None else None

        tick_age_seconds = (
            _tick_age(current_tick)
        )
        trade_tick_age_seconds = _tick_age(self._current_trade_tick_at_ms)
        book_tick_age_seconds = _tick_age(self._current_book_tick_at_ms)
        trade_fresh = bool(
            trade_conn
            and trade_tick_age_seconds is not None
            and trade_tick_age_seconds <= self._feed_freshness_seconds
        )
        book_fresh: Optional[bool] = (
            bool(
                ba_conn
                and book_tick_age_seconds is not None
                and book_tick_age_seconds <= self._feed_freshness_seconds
            )
            if self._current_stream_requires_book
            else None
        )
        feed_fresh = bool(
            session_active
            and required_channels_connected
            and trade_fresh
            and (book_fresh is not False)
        )
        if not feed_fresh:
            # A later tick can now produce one transition notification when the
            # complete feed becomes fresh again.
            with self._signalr_metrics_lock:
                self._feed_live_notified = False
        stream_start_age = (
            max(0.0, time.monotonic() - self._current_stream_started_at_monotonic)
            if self._current_stream_started_at_monotonic is not None
            else None
        )

        if not self._is_connected:
            computed_status = "UNAVAILABLE" if not self.username or not self.password else "ERROR"
        elif self._upstream_status == "RESTARTING":
            computed_status = "RECONNECTING"
        elif self._upstream_status == "ERROR":
            computed_status = "ERROR"
        elif not self._active_symbols:
            computed_status = "READY"
        elif not session_active:
            computed_status = "READY" if stream_connected else "DISCONNECTED"
        elif feed_fresh:
            computed_status = "LIVE"
        elif required_channels_connected and not feed_fresh and (
            self._current_trade_tick_at_ms is None
            or (
                self._current_stream_requires_book
                and self._current_book_tick_at_ms is None
            )
        ) and (
            stream_start_age is None or stream_start_age <= self._feed_freshness_seconds
        ):
            computed_status = "CONNECTING"
        elif required_channels_connected:
            computed_status = "STALE"
        else:
            computed_status = "RECONNECTING"

        def _iso_timestamp(value: Optional[int]) -> Optional[str]:
            if value is None:
                return None
            return datetime.fromtimestamp(value / 1000.0, timezone.utc).isoformat()

        with self._signalr_metrics_lock:
            buffered_bytes = sum(
                adapter.stats.buffered_bytes for adapter in self._signalr_adapters.values()
            )
            adapter_count = len(self._signalr_adapters)
        last_tick_ms = max(
            (
                value
                for value in (self._last_trade_tick_at_ms, self._last_book_tick_at_ms)
                if value is not None
            ),
            default=None,
        )

        return {
            "feedStatus": self._access.wire(fresh=feed_fresh, active=session_active, last_data_at=_iso_timestamp(last_tick_ms)),
            "provider": "fiinquant",
            "authenticated": self._is_connected,
            "upstream_status": computed_status,
            "trade_stream_connected": trade_conn,
            "bid_ask_stream_connected": ba_conn,
            "subscription_count": len(self._active_symbols),
            "max_subscriptions": self.max_symbols,
            "subscriptions": self.get_active_subscriptions(),
            "last_error": self._last_error,
            "feed_fresh": feed_fresh,
            "feed_freshness_seconds": self._feed_freshness_seconds,
            "latest_tick_age_seconds": tick_age_seconds,
            "trade_tick_age_seconds": trade_tick_age_seconds,
            "book_tick_age_seconds": book_tick_age_seconds,
            "trade_feed_fresh": trade_fresh,
            "book_feed_fresh": book_fresh,
            "book_stream_required": self._current_stream_requires_book,
            "last_trade_tick_at": _iso_timestamp(self._last_trade_tick_at_ms),
            "last_book_tick_at": _iso_timestamp(self._last_book_tick_at_ms),
            "last_tick_at": _iso_timestamp(last_tick_ms),
            # ---- SignalR lifecycle observability ----
            "connection_generation": self._generation,
            "stream_generation": self._stream_generation,
            "active_stream_count": len(self._owned_streams),
            "signalr_ping_threads": count_signalr_ping_threads(),
            "is_shutting_down": self._shutting_down,
            "connect_count": self._connect_count,
            "disconnect_count": self._disconnect_count,
            "stream_restart_count": self._stream_restart_count,
            "reconnect_count": self._reconnect_count,
            # Reconnects forced because a "connected" stream stopped delivering frames
            # mid-session. A climbing value means FiinQuant is dropping us silently.
            "silent_stream_reconnect_count": self._silent_stream_reconnect_count,
            "stream_watchdog_active": bool(
                self._stream_watchdog_task is not None and not self._stream_watchdog_task.done()
            ),
            "stream_silence_reconnect_seconds": self._stream_silence_reconnect_seconds,
            # How far the watchdog has widened its silence budget (0 = base). A high value
            # with silent_stream_reconnect_count climbing = the feed is genuinely gone and
            # we are now re-probing it slowly rather than every 90s.
            "watchdog_silence_escalation": self._silent_watchdog_escalation,
            "watchdog_effective_silence_budget_seconds": self._watchdog_effective_silence_budget(),
            "consecutive_stream_start_failures": self._consecutive_stream_start_failures,
            "reauth_pending": self._force_reauth,
            "seconds_since_last_auth_attempt": (
                None
                if self._last_auth_attempt_monotonic == float("-inf")
                else round(max(0.0, time.monotonic() - self._last_auth_attempt_monotonic), 1)
            ),
            "orphan_ping_threads_reaped": self._orphans_reaped,
            "signalr_adapter_supported_version": _SUPPORTED_SIGNALRCORE_VERSION,
            "signalr_adapter_runtime_version": self._signalrcore_version(),
            "signalr_adapter_active_count": adapter_count,
            "signalr_adapter_installed_count": self._signalr_adapter_installed_count,
            "signalr_buffered_bytes": buffered_bytes,
            "signalr_frame_error_count": self._signalr_frame_error_count,
            "signalr_decode_error_count": self._signalr_decode_error_count,
            "signalr_partial_timeout_count": self._signalr_partial_timeout_count,
            "signalr_buffer_overflow_count": self._signalr_buffer_overflow_count,
            "last_signalr_frame_error_kind": self._last_signalr_frame_error_kind,
            "last_signalr_frame_error_at": _iso_timestamp(self._last_signalr_frame_error_at_ms),
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

        default_from = (market_session.get_vn_now() - timedelta(days=default_days)).strftime("%Y-%m-%d")
        f_date = from_date or default_from
        t_date = to_date or market_session.get_vn_now().strftime("%Y-%m-%d")

        # Range verification: if explicit range > 365 calendar days, raise HistoricalRangeLimitError (do NOT clamp silently)
        if from_date is not None:
            try:
                dt_from = datetime.strptime(f_date, "%Y-%m-%d").date()
                dt_to = datetime.strptime(t_date, "%Y-%m-%d").date() if to_date else market_session.get_vn_now().date()
                span_days = (dt_to - dt_from).days
                now_date = market_session.get_vn_now().date()
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
                with capture_sdk_output(captured_output):
                    res = self._session.Fetch_Trading_Data(
                        realtime=False,
                        tickers=[sym],
                        fields=["open", "high", "low", "close", "volume", "value"],
                        by=by_param,
                        from_date=f_date,
                        to_date=t_date,
                        adjusted=adjusted,
                    )
                    df = res.get_data() if hasattr(res, "get_data") else res

                captured_text = captured_output.getvalue()
                if "service has expired" in captured_text.lower():
                    raise HistoricalEntitlementError("ENTITLEMENT_EXPIRED: Service has expired")
                captured_text = redact_provider_text(captured_text)
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
                        d_str = timestamp(first(r, "timestamp", "TradingDate", "date"))
                        values = {key: number(r, key, key.title()) for key in ("open", "high", "low", "close", "volume")}
                        # Incomplete bars are gaps, not fabricated OHLC or zero volume.
                        if d_str and all(v is not None for v in values.values()):
                            bars.append(
                                HistoricalBar(
                                    date=d_str,
                                    **values,
                                    value=number(r, "value", "Value", "TotalMatchValue"),
                                    adjusted=adjusted,
                                    price_basis="ADJUSTED" if adjusted else "RAW",
                                    session_date=d_str[:10],
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
                exc_str = redact_provider_text(exc)
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
                if "403" in exc_str or "Forbidden" in exc_str or "ENTITLEMENT_EXPIRED" in exc_str:
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

        return await asyncio.to_thread(self._sdk_call, "history", _fetch)

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

                records = await asyncio.to_thread(self._sdk_call, "profiles", fetch)
                def clean(value):
                    return value.strip() if isinstance(value, str) and value.strip() else None

                def first_clean(raw: Dict[str, Any], *keys: str) -> Optional[str]:
                    return next((value for key in keys if (value := clean(raw.get(key)))), None)

                by_symbol = {str(r.get("ticker", "")).strip().upper(): r
                             for r in records if isinstance(r, dict)}
                now = time.monotonic()
                for symbol in missing:
                    raw = by_symbol.get(symbol, {})
                    exchange = first_clean(raw, "exchange", "exchangeCode")
                    self._stock_profile_cache[symbol] = (now, {
                        "symbol": symbol,
                        "name": first_clean(raw, "companyName", "organizationName"),
                        "short_name": first_clean(
                            raw,
                            "shortName",
                            "companyShortName",
                            "companyAbbreviation",
                            "organizationShortName",
                        ),
                        "exchange": exchange.upper() if exchange else None,
                    })
            return [dict(self._stock_profile_cache[s][1]) for s in symbols]

    _VALUATION_TTL_SECONDS = 3600.0
    _RATIOS_TTL_SECONDS = 6 * 3600.0

    async def get_stock_valuation(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """Latest P/E and P/B per symbol.

        `MarketDepth().get_stock_valuation` returns one row per ticker per trading day; we
        keep the newest. Probed on this account: it IS entitled, unlike BasicInfor and
        MarketBreadth, so the values below are real rather than a hopeful call.
        """
        symbols = sorted({s.strip().upper() for s in symbols if s.strip()})
        if not symbols:
            return {}
        async with self._fundamentals_lock:
            now = time.monotonic()
            missing = [s for s in symbols
                       if s not in self._valuation_cache
                       or now - self._valuation_cache[s][0] >= self._VALUATION_TTL_SECONDS]
            if missing:
                if not self._session or not self._is_connected:
                    if not await self.connect():
                        raise RuntimeError("FiinQuant valuation is unavailable")
                today = market_session.get_vn_now().date()
                start = (today - timedelta(days=14)).isoformat()

                def fetch():
                    value = self._session.MarketDepth().get_stock_valuation(
                        tickers=missing, from_date=start, to_date=today.isoformat()
                    )
                    if hasattr(value, "to_dict"):
                        value = value.to_dict(orient="records")
                    return value if isinstance(value, list) else []

                records = await asyncio.to_thread(self._sdk_call, "valuation", fetch)
                newest: Dict[str, Dict[str, Any]] = {}
                for row in records:
                    if not isinstance(row, dict):
                        continue
                    sym = str(row.get("ticker", "")).strip().upper()
                    if not sym:
                        continue
                    stamp = str(row.get("timestamp") or "")
                    prior = newest.get(sym)
                    if prior is None or stamp >= str(prior.get("as_of") or ""):
                        newest[sym] = {
                            "symbol": sym,
                            "pe": number(row, "pe"),
                            "pb": number(row, "pb"),
                            "as_of": stamp[:10] or None,
                        }
                stamped = time.monotonic()
                for sym in missing:
                    # Cache the miss too, so an unlisted symbol is not retried every request.
                    self._valuation_cache[sym] = (
                        stamped, newest.get(sym, {"symbol": sym, "pe": None, "pb": None, "as_of": None}),
                    )
            return {s: dict(self._valuation_cache[s][1]) for s in symbols}

    async def get_financial_ratios(self, symbol: str, quarters: int = 8) -> List[Dict[str, Any]]:
        """Recent quarterly statement lines, oldest first.

        This account's `get_ratios` returns Revenue, AttributeToParentCompany (net profit
        attributable to the parent) and EBIT, and nothing else: passing an explicit
        `fields` list makes the SDK raise internally and yield nothing, so the full-node
        call is deliberate. ROA / ROE / ROIC / margins / EPS are simply not served here.
        """
        sym = symbol.strip().upper()
        if not sym:
            return []
        async with self._fundamentals_lock:
            cached = self._ratios_cache.get(sym)
            if cached and time.monotonic() - cached[0] < self._RATIOS_TTL_SECONDS:
                return [dict(r) for r in cached[1]]
            if not self._session or not self._is_connected:
                if not await self.connect():
                    raise RuntimeError("FiinQuant financial ratios are unavailable")
            today = market_session.get_vn_now().date()
            years = sorted({today.year - offset for offset in range((quarters // 4) + 2)})

            def fetch():
                value = self._session.FundamentalAnalysis().get_ratios(
                    tickers=[sym], years=years, quarters=[1, 2, 3, 4], type="consolidated"
                )
                return value if isinstance(value, list) else []

            records = await asyncio.to_thread(self._sdk_call, "fundamentals", fetch)
            rows: List[Dict[str, Any]] = []
            for row in records:
                if not isinstance(row, dict):
                    continue
                ratios = row.get("ratios") or {}
                year, quarter = row.get("year"), row.get("quarter")
                if year is None or quarter is None:
                    continue
                revenue = number(ratios, "Revenue")
                profit = number(ratios, "AttributeToParentCompany")
                rows.append({
                    "period": f"{int(year)}Q{int(quarter)}",
                    "year": int(year),
                    "quarter": int(quarter),
                    "revenue": revenue,
                    "net_profit": profit,
                    "ebit": number(ratios, "EBIT"),
                    # The one margin these three lines can support honestly.
                    "net_margin": (profit / revenue) if revenue and profit is not None and revenue > 0 else None,
                })
            rows.sort(key=lambda r: (r["year"], r["quarter"]))
            rows = rows[-quarters:]
            self._ratios_cache[sym] = (time.monotonic(), rows)
            return [dict(r) for r in rows]

    async def get_session_reference_data(
        self, symbols: List[str], session_date: date
    ) -> Dict[str, Dict[str, Any]]:
        """Fetch explicitly dated exchange references and bands without new streams."""
        clean_symbols = sorted({s.strip().upper() for s in symbols if s.strip()})
        if not clean_symbols:
            return {}
        async with self._reference_lock:
            if not self._session or not self._is_connected:
                if not await self.connect():
                    raise RuntimeError("FiinQuant session reference data is unavailable")

            def records(value: Any) -> List[Dict[str, Any]]:
                if value is None:
                    return []
                if hasattr(value, "get_data"):
                    value = value.get_data()
                if hasattr(value, "reset_index"):
                    try:
                        value = value.reset_index()
                    except (TypeError, ValueError):
                        pass
                if hasattr(value, "to_dict"):
                    try:
                        return value.to_dict(orient="records")
                    except TypeError:
                        value = value.to_dict()
                if isinstance(value, list):
                    return [dict(item) for item in value if isinstance(item, dict)]
                return [dict(value)] if isinstance(value, dict) else []

            def key(row: Dict[str, Any]) -> str:
                return str(row.get("ticker") or row.get("Ticker") or "").strip().upper()

            def stamp(row: Dict[str, Any]) -> str:
                return str(
                    row.get("timestamp")
                    or row.get("TradingDate")
                    or row.get("tradingDate")
                    or row.get("date")
                    or ""
                )

            def number(row: Dict[str, Any], *names: str) -> Optional[float]:
                for name in names:
                    value = row.get(name)
                    if value is None:
                        continue
                    try:
                        return float(value)
                    except (TypeError, ValueError):
                        continue
                return None

            def fetch() -> Dict[str, Dict[str, Any]]:
                band_rows: List[Dict[str, Any]] = []
                captured = io.StringIO()
                with capture_sdk_output(captured):
                    try:
                        stats = self._session.PriceStatistics()
                        for start in range(0, len(clean_symbols), 100):
                            result = stats.get_ceilingfloor(
                                tickers=clean_symbols[start:start + 100],
                                from_date=session_date.isoformat(),
                                to_date=session_date.isoformat(),
                            )
                            band_rows.extend(records(result))
                    except Exception as exc:
                        logger.warning("FiinQuant session price bands unavailable: %s", exc)

                bands_by: Dict[str, Dict[str, Any]] = {}
                for row in band_rows:
                    symbol = key(row) or (clean_symbols[0] if len(clean_symbols) == 1 else "")
                    if not symbol or stamp(row)[:10] != session_date.isoformat():
                        continue
                    if symbol not in bands_by or stamp(row) > stamp(bands_by[symbol]):
                        bands_by[symbol] = row

                result: Dict[str, Dict[str, Any]] = {}
                for symbol in clean_symbols:
                    band = bands_by.get(symbol, {})
                    reference = number(
                        band, "referenceValue", "referencePrice", "Reference", "ReferencePrice"
                    )
                    # Prior close is not confirmed current REF.
                    ceiling = number(band, "ceilingValue", "ceilingPrice", "CeilingPrice")
                    floor = number(band, "floorValue", "floorPrice", "FloorPrice")
                    if reference is None and ceiling is None and floor is None:
                        continue
                    result[symbol] = {
                        "session_date": session_date.isoformat(),
                        "reference_price": reference,
                        "ceiling_price": ceiling,
                        "floor_price": floor,
                    }
                return result

            try:
                return await asyncio.to_thread(self._sdk_call, "reference", fetch)
            finally:
                self._tame_sdk_side_effects()

    async def get_session_trade_snapshot(
        self, symbols: List[str], session_date: date
    ) -> Dict[str, Dict[str, Any]]:
        """Today's forming 1d bar (last price, session OHLC / volume / value) per symbol
        via the ``realtime=False`` snapshot path. Seeds the trade group for instruments
        that have not yet ticked on ``Trading_Data_Stream`` this session — sparsely-traded
        covered warrants show bid/ask live but no trade until this fills them.

        ``by='1d', from_date=<recent>, to_date=<today>, lasted=True`` returns 2 rows/ticker:
        the prior close (reference) and today's live forming bar. ``period`` mode is NOT
        used — it truncates to the host clock and returns yesterday only.
        """
        clean = sorted({s.strip().upper() for s in symbols if s and s.strip()})
        if not clean:
            return {}
        sd = session_date.isoformat()
        from_date = (session_date - timedelta(days=6)).isoformat()

        async with self._reference_lock:
            if not self._session or not self._is_connected:
                if not await self.connect():
                    raise RuntimeError("FiinQuant session trade snapshot is unavailable")

            def records(value: Any) -> List[Dict[str, Any]]:
                if value is None:
                    return []
                if hasattr(value, "get_data"):
                    value = value.get_data()
                if hasattr(value, "reset_index"):
                    try:
                        value = value.reset_index()
                    except (TypeError, ValueError):
                        pass
                if hasattr(value, "to_dict"):
                    try:
                        return value.to_dict(orient="records")
                    except TypeError:
                        value = value.to_dict()
                if isinstance(value, list):
                    return [dict(x) for x in value if isinstance(x, dict)]
                return [dict(value)] if isinstance(value, dict) else []

            def stamp(row: Dict[str, Any]) -> str:
                return str(first(row, "timestamp", "Timestamp", "TradingDate", "tradingDate") or "")

            def fetch() -> Dict[str, Dict[str, Any]]:
                rows: List[Dict[str, Any]] = []
                captured = io.StringIO()
                with capture_sdk_output(captured):
                    try:
                        for start in range(0, len(clean), 100):
                            res = self._session.Fetch_Trading_Data(
                                realtime=False,
                                tickers=clean[start:start + 100],
                                fields=["open", "high", "low", "close", "volume", "value"],
                                adjusted=False,
                                by="1d",
                                from_date=from_date,
                                to_date=sd,
                                lasted=True,
                            )
                            rows.extend(records(res))
                    except Exception as exc:  # noqa: BLE001 - never break the poll loop
                        logger.warning("FiinQuant session trade snapshot fetch failed: %s", exc)
                        return {}

                by_ticker: Dict[str, List[Dict[str, Any]]] = {}
                for row in rows:
                    tk = str(first(row, "ticker", "Ticker") or "").upper()
                    if tk:
                        by_ticker.setdefault(tk, []).append(row)

                out: Dict[str, Dict[str, Any]] = {}
                for sym, ticker_rows in by_ticker.items():
                    ticker_rows.sort(key=stamp)
                    positive = [r for r in ticker_rows if (number(r, "close", "Close") or 0) > 0]
                    today = [r for r in positive if stamp(r)[:10] == sd]
                    if not today:
                        continue
                    bar = today[-1]
                    out[sym] = {
                        "last_price": number(bar, "close", "Close"),
                        "open_price": number(bar, "open", "Open"),
                        "high_price": number(bar, "high", "High"),
                        "low_price": number(bar, "low", "Low"),
                        "total_volume": number(bar, "volume", "Volume"),
                        "trading_value": number(bar, "value", "Value"),
                        "reference_price": number(bar, "referencePrice", "referenceValue"),
                        "as_of": stamp(bar),
                    }
                return out

            try:
                return await asyncio.to_thread(self._sdk_call, "session_snapshot", fetch)
            finally:
                self._tame_sdk_side_effects()

    _INDEX_GROUPS = ("VN30", "VNINDEX", "VNFINLEAD", "VNDIAMOND")
    # HOSE daily price limit; a constituent within this of its reference move counts as
    # at-ceiling / at-floor without a per-ticker band lookup.
    _HOSE_LIMIT = 0.0699
    # HOSE continuous session opens 09:00 ICT; mirrors the frontend's own SESSION_OPEN_MIN
    # (market_overview_strip.tsx) - used only to sanity-check a cached sparkline's start.
    _SESSION_OPEN_MIN = 9 * 60

    def _cache_ttl(self, active_ttl: float, *, settled: bool = True) -> float:
        """TTL for a cache that only needs refreshing while the market can move: short and
        fixed in-session, but stretched to cover the whole closed stretch (lunch, evening,
        weekend, holiday) outside it — nothing changes until trading resumes, so there is
        nothing new to fetch. Mirrors ``_compute_reconnect_delay``'s reasoning, but without
        that method's 300s ceiling: a data cache (unlike a connection health check) has no
        reason to poll while closed at all.

        ``settled=False`` caps this at ``active_ttl`` regardless of session state — for a
        cached result that's known incomplete (e.g. built before the background breadth /
        stock-leaders sweep finished), stretching the TTL would strand that gap for the
        entire closed stretch instead of the few seconds a retry actually needs.
        """
        if self._market_is_active() or not settled:
            return active_ttl
        try:
            # Never past the 08:00 display rollover. The stretch is only sound while
            # "nothing has changed" is true, and at 08:00 the app moves to a new session:
            # holding a previous-session payload past that point makes the index cards
            # disagree with the watchlist for the whole 08:00-09:00 hour.
            stretch = min(
                float(self._seconds_to_next_session()),
                float(self._seconds_to_display_rollover()),
            )
            return max(0.0, stretch)
        except Exception:  # noqa: BLE001 - never let a calendar bug wedge the cache
            return active_ttl

    def _ensure_breadth_refresh(self) -> None:
        """Kick a background breadth recompute if the cache is stale and none is running."""
        if self._access.blocked("breadth"):
            return
        ttl = self._cache_ttl(60.0)
        from app.market_data.trading_calendar import reference_session_date
        if getattr(self, "_breadth_session", None) != reference_session_date(market_session.get_vn_now()).isoformat():
            self._breadth_cache_at = 0
        if self._breadth_cache_at and time.monotonic() - self._breadth_cache_at < ttl:
            return
        if self._breadth_task is not None and not self._breadth_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        logger.info("FiinQuant index breadth sweep: scheduling background refresh")
        self._breadth_task = loop.create_task(self._refresh_index_breadth())

    async def _refresh_index_breadth(self) -> None:
        started = time.monotonic()
        from app.market_data.trading_calendar import reference_session_date
        requested_session = reference_session_date(market_session.get_vn_now()).isoformat()
        try:
            breadth, stock_leaders = await asyncio.to_thread(self._sdk_call, "breadth", self._compute_index_breadth)
        except Exception as exc:  # noqa: BLE001 - breadth is optional, never fatal
            logger.warning("FiinQuant index breadth refresh failed: %s: %s", type(exc).__name__, exc)
            return
        if requested_session != reference_session_date(market_session.get_vn_now()).isoformat():
            return
        if breadth:
            self._breadth_session = requested_session
            self._breadth_as_of = market_session.get_vn_now().isoformat()
            self._breadth_cache = breadth
            self._stock_leaders_cache = stock_leaders
            self._breadth_cache_at = time.monotonic()
            logger.info(
                "FiinQuant index breadth sweep done in %.1fs: %s",
                time.monotonic() - started,
                {g: b.get("totalStockUpPrice", 0) for g, b in breadth.items()},
            )
        else:
            logger.warning("FiinQuant index breadth sweep returned no data")

    def _compute_index_breadth(
        self,
    ) -> tuple[Dict[str, Dict[str, int]], List[Dict[str, Any]]]:
        """Per-group advancing/declining/unchanged/ceiling/floor + the top-volume stock
        leaders, from one `PriceStatistics().get_overview` sweep of the HOSE constituents
        (the SDK issues one request per ticker — hence background-only). `get_overview` is
        a session-total endpoint so the leaders stay populated after the close, unlike the
        1d bar fetch. `percentPriceChange` gives direction; VWAP = value / volume.
        """
        if not self._session:
            return {}, []
        from app.market_data.trading_calendar import reference_session_date
        vn_today = reference_session_date(market_session.get_vn_now()).isoformat()
        captured = io.StringIO()
        with capture_sdk_output(captured):
            members: Dict[str, set] = {}
            for grp in self._INDEX_GROUPS:
                try:
                    value = self._session.TickerList(ticker=grp)
                    members[grp] = {str(x).strip().upper() for x in value if str(x).strip()}
                except Exception as exc:  # noqa: BLE001
                    logger.warning("FiinQuant %s constituents unavailable: %s", grp, exc)
                    members[grp] = set()
            universe = sorted(set().union(*members.values())) if members else []
            if not universe:
                return {}, []
            stats: Dict[str, Dict[str, Any]] = {}
            for start in range(0, len(universe), 100):
                if not self._session:  # session retired mid-sweep (reconnect / shutdown)
                    break
                try:
                    raw = self._session.PriceStatistics().get_overview(
                        tickers=universe[start:start + 100], time_filter="Daily",
                        from_date=vn_today, to_date=vn_today,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("FiinQuant get_overview batch failed: %s", exc)
                    continue
                if hasattr(raw, "get_data"):
                    raw = raw.get_data()
                rows = raw.to_dict(orient="records") if hasattr(raw, "to_dict") else list(raw or [])
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    tk = str(row.get("ticker") or row.get("Ticker") or "").upper()
                    if tk:
                        stats[tk] = row

        def fnum(row: Dict[str, Any], *names: str) -> Optional[float]:
            for name in names:
                v = row.get(name)
                if isinstance(v, (int, float)):
                    return float(v)
            return None

        breadth: Dict[str, Dict[str, int]] = {}
        for grp, syms in members.items():
            up = down = flat = ceil_n = floor_n = 0
            for s in syms:
                p = fnum(stats.get(s, {}), "percentPriceChange")
                if p is None:
                    continue
                if p >= self._HOSE_LIMIT:
                    ceil_n += 1
                elif p <= -self._HOSE_LIMIT:
                    floor_n += 1
                if p > 0:
                    up += 1
                elif p < 0:
                    down += 1
                else:
                    flat += 1
            breadth[grp] = {
                "totalStockUpPrice": up, "totalStockDownPrice": down,
                "totalStockNoChangePrice": flat, "totalStockOverCeiling": ceil_n,
                "totalStockUnderFloor": floor_n,
            }

        def leader_row(tk: str, row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            vol = fnum(row, "totalMatchVolume")
            val = fnum(row, "totalMatchValue")
            if not vol or vol <= 0:
                return None
            p = fnum(row, "percentPriceChange")
            return {
                "symbol": tk, "volume": vol,
                "price": fnum(row, "close", "price", "lastPrice"),
                "reference": None, "ceiling": None, "floor": None,
                "market_state": (
                    "CEILING" if p is not None and p >= self._HOSE_LIMIT
                    else "FLOOR" if p is not None and p <= -self._HOSE_LIMIT
                    else "UP" if p and p > 0 else "DOWN" if p and p < 0
                    else "REFERENCE" if p == 0 else "UNAVAILABLE"
                ),
                "as_of": str(row.get("timestamp") or ""),
            }

        rows = [
            row for tk in stats
            for row in (leader_row(tk, stats[tk]),) if row is not None
        ]
        rows.sort(key=lambda x: x["volume"], reverse=True)
        return breadth, rows[:5]

    def _sparkline_settled(self, cache: Dict[str, Any]) -> bool:
        """False if any index's chart is missing its early bars - a fetch that raced a
        FiinQuant hiccup and came back starting well after 09:00 ICT, e.g. from ~11:05
        instead (confirmed live: production served exactly this, frozen for the rest of
        the closed stretch once the overview-cache TTL stretch made it "settled" by the
        stock-leaders check alone). >20 min of slack covers a merely-late opening tick
        without falsely flagging a genuinely complete session."""
        for item in cache.get("indices", []):
            sparkline = item.get("sparkline") or []
            if not sparkline:
                continue
            first = sparkline[0]
            ts = first.get("timestamp") if isinstance(first, dict) else None
            if not ts:
                continue
            try:
                parsed = datetime.fromisoformat(ts)
                first_minutes = parsed.hour * 60 + parsed.minute
            except (ValueError, TypeError):
                continue
            if first_minutes > self._SESSION_OPEN_MIN + 20:
                return False
        return True

    async def get_market_overview(self, cw_symbols: List[str]) -> Dict[str, Any]:
        """Read the four index cards and HOSE volume leaders without new streams.

        Snapshot reads only (no stream mutations). ``MarketBreadth`` is not on this
        account, so breadth + the stock volume leaders are maintained on their own slow
        background cadence (`_refresh_index_breadth`). Payload cached ~15 s in-session,
        and effectively until the next session opens outside it (see ``_cache_ttl``) -
        unless the cached payload still lacks stock leaders, or an index chart is missing
        its early bars, because a sweep/fetch hadn't finished or hiccuped when it was
        built - in which case it stays on the short TTL until a clean result lands.
        """
        from app.market_data.trading_calendar import reference_session_date
        request_display_session = reference_session_date(market_session.get_vn_now()).isoformat()
        self._ensure_breadth_refresh()
        settled = bool(self._overview_cache) and (
            self._overview_cache.get("components", {}).get("top_stock_volume") == "AVAILABLE"
        ) and self._sparkline_settled(self._overview_cache)
        ttl = self._cache_ttl(60.0, settled=settled)
        if (
            self._overview_cache
            and self._session
            and self._is_connected
            and self._overview_cache.get("display_session") == reference_session_date(market_session.get_vn_now()).isoformat()
            and time.monotonic() - self._overview_cache_at < ttl
        ):
            return self._overview_cache
        async with self._overview_lock:
            if (
                self._overview_cache
                and self._session
                and self._is_connected
                and self._overview_cache.get("display_session") == reference_session_date(market_session.get_vn_now()).isoformat()
            and time.monotonic() - self._overview_cache_at < ttl
            ):
                return self._overview_cache
            if not self._session or not self._is_connected:
                try:
                    connected = await self.connect()
                except Exception as exc:  # stale cache remains useful during reconnect failures
                    logger.warning("FiinQuant market overview reconnect failed: %s", exc)
                    connected = False
                if not connected:
                    cached = self._stale_market_overview_payload()
                    if cached is not None:
                        return cached
                    raise RuntimeError("FiinQuant market overview is unavailable")

            index_symbols = ["VN30", "VNINDEX", "VNFINLEAD", "VNDIAMOND"]

            def records(value: Any) -> List[Dict[str, Any]]:
                if value is None:
                    return []
                if hasattr(value, "get_data"):
                    value = value.get_data()
                if hasattr(value, "reset_index"):
                    try:
                        value = value.reset_index()
                    except (TypeError, ValueError):
                        pass
                if hasattr(value, "to_dict"):
                    try:
                        return value.to_dict(orient="records")
                    except TypeError:
                        value = value.to_dict()
                if isinstance(value, list):
                    return [dict(x) for x in value if isinstance(x, dict)]
                return [dict(value)] if isinstance(value, dict) else []

            def fetch_rows(tickers: List[str], *, by: str, period: int | None = None,
                           from_date: str | None = None, to_date: str | None = None) -> List[Dict[str, Any]]:
                rows: List[Dict[str, Any]] = []
                for start in range(0, len(tickers), 100):
                    result = self._session.Fetch_Trading_Data(
                        realtime=False,
                        tickers=tickers[start:start + 100],
                        fields=["close", "volume", "value"],
                        adjusted=False,
                        by=by,
                        lasted=True,
                        **({"period": period} if period is not None else {
                            "from_date": from_date, "to_date": to_date,
                        }),
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

            def key(row: Dict[str, Any]) -> str:
                return str(first(row, "ticker", "Ticker") or "").upper()

            def stamp(row: Dict[str, Any]) -> str:
                return timestamp(first(row, "timestamp", "TradingDate", "tradingDate")) or ""

            def num(row: Dict[str, Any], *names: str) -> Optional[float]:
                return number(row, *names)

            def actual_prices(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
                # Pre-open OHLC=0 resets are not executed prices. Keep legitimate
                # zero volume/value on positive-price observations unchanged.
                return [row for row in rows if (num(row, "close", "Close") or 0) > 0 and stamp(row)]

            def build() -> Dict[str, Any]:
                captured = io.StringIO()
                unavailable_components: set[str] = set()
                clean_cws = sorted({s.strip().upper() for s in cw_symbols if s.strip()})
                daily: List[Dict[str, Any]] = []
                intraday: List[Dict[str, Any]] = []
                bands: List[Dict[str, Any]] = []
                with capture_sdk_output(captured):
                    try:
                        # Only the 4 index symbols + the watched CWs — the ~430 HOSE
                        # constituents (breadth + stock leaders) are a separate background
                        # sweep because the SDK issues one request per ticker.
                        # 20 days, not 6: a thinly-traded CW can go a week+ between prints
                        # (confirmed live — some only show one bar in a 6-day window), and
                        # the CW-leaders `reference` lookup needs a PRIOR bar to exist in
                        # the fetched range or it falls through to UNAVAILABLE (no color).
                        vn_today = market_session.get_vn_now().date()
                        daily = actual_prices(fetch_rows(
                            sorted(set(index_symbols + clean_cws)), by="1d",
                            from_date=(vn_today - timedelta(days=20)).isoformat(),
                            to_date=vn_today.isoformat(),
                        ))
                    except Exception as exc:
                        unavailable_components.add("daily")
                        logger.warning("FiinQuant overview daily snapshot unavailable: %s", exc)
                    try:
                        # Target the OBSERVED session (rolls at 08:00 ICT), not the newest
                        # daily bar — FiinQuant lags the daily bar after the close, but the
                        # session's 5m buckets are still there. Query in explicit ICT so the
                        # SDK's host-clock `to` truncation doesn't cut a 09:xx session.
                        from app.market_data.session_reference import reference_session_date
                        index_day = max(
                            [reference_session_date(market_session.get_vn_now()).isoformat(),
                             *(stamp(r)[:10] for r in daily if key(r) in index_symbols)],
                            default=market_session.get_vn_now().date().isoformat(),
                        )
                        end = min(f"{index_day} 15:00", market_session.get_vn_now().strftime("%Y-%m-%d %H:%M"))
                        if end >= f"{index_day} 09:00":
                            intraday = actual_prices(fetch_rows(index_symbols, by="5m",
                                from_date=f"{index_day} 09:00", to_date=end))
                    except Exception as exc:
                        unavailable_components.add("intraday")
                        logger.warning("FiinQuant overview intraday snapshot unavailable: %s", exc)
                    index_dates = [stamp(r)[:10] for r in daily + intraday if key(r) in index_symbols]
                    session_date = max(index_dates or [stamp(r)[:10] for r in daily], default="")
                    try:
                        bands = fetch_price_bands(clean_cws, session_date) if session_date else []
                    except Exception as exc:
                        unavailable_components.add("bands")
                        logger.warning("FiinQuant price bands unavailable for overview: %s", exc)
                        bands = []
                if not self._stock_leaders_cache:
                    unavailable_components.add("stock_universe")
                if not daily:
                    unavailable_components.add("daily")
                if not intraday:
                    unavailable_components.add("intraday")
                if not bands:
                    unavailable_components.add("bands")

                daily_by: Dict[str, List[Dict[str, Any]]] = {}
                for row in daily:
                    if key(row): daily_by.setdefault(key(row), []).append(row)
                intra_by: Dict[str, List[Dict[str, Any]]] = {}
                for row in intraday:
                    if key(row): intra_by.setdefault(key(row), []).append(row)
                bands_by: Dict[str, Dict[str, Any]] = {}
                for row in bands:
                    symbol = key(row)
                    if symbol and (symbol not in bands_by or stamp(row) > stamp(bands_by[symbol])):
                        bands_by[symbol] = row

                # Breadth is maintained on its own background cadence (see
                # `_refresh_index_breadth`) because it costs ~430 per-ticker requests.
                breadth_by = dict(self._breadth_cache) if getattr(self, "_breadth_session", None) == session_date else {}
                if not any(sum(b.values()) for b in breadth_by.values()):
                    unavailable_components.add("breadth")

                indices = []
                for symbol in index_symbols:
                    bars = sorted(daily_by.get(symbol, []), key=stamp)
                    intraday_bars = sorted(intra_by.get(symbol, []), key=stamp)
                    latest_day = session_date
                    intraday_bars = [x for x in intraday_bars if stamp(x)[:10] == latest_day]
                    session_bars = [row for row in bars if stamp(row)[:10] == latest_day]
                    prior_bars = [row for row in bars if stamp(row)[:10] < latest_day]
                    latest = session_bars[-1] if session_bars else {}
                    previous = prior_bars[-1] if prior_bars else {}
                    current = max([latest, *intraday_bars], key=stamp)
                    close, reference = num(current, "close", "Close"), num(previous, "close", "Close")
                    # FiinQuant can lag the index daily bar after the close; the 5m buckets
                    # for the session are still there, so sum them for VOL / VAL.
                    session_volume = num(latest, "volume", "Volume")
                    session_value = num(latest, "value", "Value")
                    if session_volume is None and intraday_bars:
                        vols = [num(x, "volume", "Volume") for x in intraday_bars]
                        vals = [num(x, "value", "Value") for x in intraday_bars]
                        session_volume = sum(v for v in vols if v is not None) or None
                        session_value = sum(v for v in vals if v is not None) or None
                    change = close - reference if close is not None and reference is not None else None
                    pct = change / reference * 100 if change is not None and reference else None
                    b = breadth_by.get(symbol, {})
                    has_breadth = bool(b) and sum(b.values()) > 0
                    if not has_breadth:
                        b = {}
                    card_state = (
                        "AVAILABLE" if close is not None and has_breadth and bool(intraday_bars)
                        else "PARTIAL" if close is not None or has_breadth
                        else "UNAVAILABLE"
                    )
                    indices.append({
                        "symbol": symbol, "value": close, "change": change, "change_percent": pct,
                        "volume": session_volume, "trading_value": session_value,
                        "reference": reference,
                        "advancing": num(b, "totalStockUpPrice"), "ceiling": num(b, "totalStockOverCeiling"),
                        "unchanged": num(b, "totalStockNoChangePrice"), "declining": num(b, "totalStockDownPrice"),
                        "floor": num(b, "totalStockUnderFloor"), "as_of": stamp(current) or None,
                        "session_date": latest_day or None,
                        "update_mode": "POLLED",
                        "partial_reasons": [reason for reason, missing in (
                            ("PRICE_UNAVAILABLE", close is None),
                            ("REFERENCE_UNAVAILABLE", reference is None),
                            ("INTRADAY_UNAVAILABLE", not intraday_bars),
                            ("BREADTH_UNAVAILABLE", not has_breadth),
                        ) if missing],
                        "sparkline": [{"timestamp": stamp(x), "value": num(x, "close", "Close"),
                                       "reference": reference,
                                       "volume": num(x, "volume", "Volume")} for x in intraday_bars
                                      if num(x, "close", "Close") is not None],
                        "provenance": {
                            "price": {"source": "FIINQUANT", "as_of": stamp(current) or None,
                                      "session_date": latest_day or None},
                            "totals": {"source": "FIINQUANT", "as_of": stamp(latest) or None,
                                       "session_date": latest_day or None,
                                       "availability": "AVAILABLE" if latest else "UNAVAILABLE"},
                            "breadth": {"source": "DERIVED_CONSTITUENTS", "as_of": getattr(self, "_breadth_as_of", None),
                                        "session_date": getattr(self, "_breadth_session", None),
                                        "availability": "AVAILABLE" if has_breadth else "UNAVAILABLE"},
                            "sparkline": {"source": "FIINQUANT", "as_of": stamp(intraday_bars[-1]) if intraday_bars else None,
                                          "session_date": latest_day or None, "timeframe": "5m",
                                          "availability": "AVAILABLE" if intraday_bars else "UNAVAILABLE"},
                        },
                        "availability": card_state,
                    })

                def leaders(universe: List[str]) -> List[Dict[str, Any]]:
                    out = []
                    for symbol in universe:
                        bars = sorted(daily_by.get(symbol, []), key=stamp)
                        session_bars = [row for row in bars if stamp(row)[:10] == session_date]
                        # After the close FiinQuant lags the CW daily bar; fall back to the
                        # most recent one so the panel shows the last session, never empty.
                        if not session_bars:
                            session_bars = bars[-1:]
                        if not session_bars:
                            continue
                        row = session_bars[-1]
                        row_day = stamp(row)[:10]
                        prior_bars = [b for b in bars if stamp(b)[:10] < row_day]
                        previous = prior_bars[-1] if prior_bars else {}
                        volume = num(row, "volume", "Volume")
                        if volume is None: continue
                        price = num(row, "close", "Close")
                        reference = num(row, "referencePrice", "referenceValue")
                        band_row = bands_by.get(symbol, {})
                        if stamp(band_row)[:10] != session_date:
                            band_row = {}
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
                index_states = {item["availability"] for item in indices}
                breadth_states = {item["provenance"]["breadth"]["availability"] for item in indices}
                overall = (
                    "AVAILABLE"
                    if index_states == {"AVAILABLE"} and not unavailable_components
                    else "UNAVAILABLE"
                    if index_states == {"UNAVAILABLE"} and not daily
                    else "PARTIAL"
                )
                # Stock leaders: background get_overview sweep (session totals, survive the
                # close). CW leaders: the local 1d fetch (get_overview omits CWs), which
                # falls back to the most recent bar per CW so the panel is never empty.
                stock_leaders = list(self._stock_leaders_cache) if getattr(self, "_breadth_session", None) == session_date else []
                cw_leaders = leaders(clean_cws)
                return {
                    "display_session": request_display_session,
                    "indices": indices,
                    "top_stock_volume": stock_leaders,
                    "top_cw_volume": cw_leaders,
                    "as_of": as_of,
                    "market_session_active": self._market_is_active(),
                    "market_phase": market_session.get_market_phase().value,
                    "stock_scope": "HOSE (VNINDEX constituents)",
                    "cw_scope": "active CW registry",
                    "source": "FIINQUANT",
                    "availability": overall,
                    "components": {
                        "indices": "UNAVAILABLE" if index_states == {"UNAVAILABLE"} else (
                            "AVAILABLE" if index_states == {"AVAILABLE"} else "PARTIAL"
                        ),
                        "top_stock_volume": "AVAILABLE" if stock_leaders else "UNAVAILABLE",
                        "top_cw_volume": "AVAILABLE" if cw_leaders else "UNAVAILABLE",
                        "breadth": "AVAILABLE" if breadth_states == {"AVAILABLE"} else (
                            "UNAVAILABLE" if breadth_states == {"UNAVAILABLE"} else "PARTIAL"
                        ),
                        "bands": "UNAVAILABLE" if "bands" in unavailable_components else "AVAILABLE",
                    },
                }

            try:
                result = await asyncio.to_thread(self._sdk_call, "overview", build)
            except Exception:
                cached = self._stale_market_overview_payload()
                if cached is not None:
                    return cached
                raise
            finally:
                self._tame_sdk_side_effects()
            self._overview_cache, self._overview_cache_at = result, time.monotonic()
            return result

    def _stale_market_overview_payload(self) -> Optional[Dict[str, Any]]:
        """Return a payload-safe copy of the last usable overview during an outage."""

        cached = self._overview_cache
        if not isinstance(cached, dict) or not any(
            cached.get(key) for key in ("indices", "top_stock_volume", "top_cw_volume")
        ):
            return None

        result = copy.deepcopy(cached)
        age_seconds = max(0.0, time.monotonic() - self._overview_cache_at)
        result.update({
            "source": "FIINQUANT_CACHE",
            "availability": "PARTIAL",
            "freshness": "STALE",
            "stale": True,
            "cache_age_seconds": round(age_seconds, 3),
            "market_session_active": self._market_is_active(),
        })
        for key in ("indices", "top_stock_volume", "top_cw_volume"):
            for item in result.get(key, []):
                if not isinstance(item, dict):
                    continue
                item["stale"] = True
                if item.get("availability") == "AVAILABLE":
                    item["availability"] = "PARTIAL"
        components = result.get("components")
        if isinstance(components, dict):
            result["components"] = {
                key: "PARTIAL" if value == "AVAILABLE" else value
                for key, value in components.items()
            }
            result["components"]["provider"] = "UNAVAILABLE"
        return result
