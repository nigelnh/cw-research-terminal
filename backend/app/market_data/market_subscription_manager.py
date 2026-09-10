import asyncio
import logging
from datetime import date, datetime
from time import monotonic
from typing import Set, List, Dict, Any, Callable, Optional, Tuple, TYPE_CHECKING

from app.core.config import settings
from app.market_data.market_session import market_session, VN_TZ
from app.market_data.live_bar_builder import live_bar_builder
from app.market_data.traded_log import traded_log
from app.market_data.market_state import MarketState, market_state
from app.market_data.market_schemas import CanonicalQuote
from app.market_data.market_state_store import MarketStateStore, NullMarketStateStore
from app.market_data.redis_market_state_store import RedisMarketStateStore
from app.market_data.session_reference import reference_session_date, refresh_session_references
from app.market_data.providers.base_market_provider import MarketDataProvider
from app.market_data.providers.provider_factory import create_market_provider

if TYPE_CHECKING:
    from app.instruments.research_universe import ResolvedResearchUniverse

logger = logging.getLogger(__name__)

TupleBoolStr = Tuple[bool, str]
_REFERENCE_RETRY_COOLDOWN_SECONDS = 30.0

# Global secondary warm cache store
market_state_store: MarketStateStore = (
    RedisMarketStateStore() if settings.REDIS_ENABLED else NullMarketStateStore()
)


class SubscriptionManager:
    """
    Coordinates active real-time market data subscriptions, deduplication,
    capacity bounds enforcement, and debounced stream restarts.
    """

    def __init__(
        self,
        provider: Optional[MarketDataProvider] = None,
        state: Optional[MarketState] = None,
        store: Optional[MarketStateStore] = None,
        max_symbols: Optional[int] = None,
        debounce_ms: Optional[int] = None,
    ):
        self.state = state or market_state
        self.store = store or market_state_store
        self.max_symbols = max_symbols or settings.MARKET_DATA_MAX_SYMBOLS
        self.debounce_ms = debounce_ms if debounce_ms is not None else settings.MARKET_DATA_DEBOUNCE_MS

        self.provider = provider or create_market_provider(max_symbols=self.max_symbols)

        self._desired_symbols: Set[str] = set()
        self._active_symbols: Set[str] = set()
        self._server_universe_symbols: Set[str] = set()
        self._server_universe_health: Dict[str, Any] = {
            "status": "DEGRADED",
            "ownership": "server",
            "expected_size": 30,
            "configured_size": 0,
            "eligible_size": 0,
            "expected_stocks": 3,
            "stock_count": 0,
            "expected_covered_warrants": 27,
            "covered_warrant_count": 0,
            "complete": False,
            "issues": [{"symbol": "__UNIVERSE__", "reason": "not_configured"}],
        }
        self._server_owned = False
        self._debounce_task: Optional[asyncio.Task] = None
        self._reference_refresh_task: Optional[asyncio.Task] = None
        self._session_clock_task: Optional[asyncio.Task] = None
        self._session_trade_poll_task: Optional[asyncio.Task] = None
        self._last_clock_phase: Optional[tuple[str, str]] = None
        self._reference_refresh_session: Optional[str] = None
        self._reference_attempt_session: Optional[str] = None
        self._reference_retry_at = 0.0
        self._patch_listeners: List[Callable[[Dict[str, Any]], None]] = []
        self._status_listeners: List[Callable[[], None]] = []
        self._update_listeners: List[Callable[[str, CanonicalQuote], None]] = []

        # Register provider event callback
        self.provider.set_event_callback(self._on_provider_event)
        set_status_callback = getattr(self.provider, "set_status_callback", None)
        if callable(set_status_callback):
            set_status_callback(self._notify_status_change)

    def register_patch_listener(self, listener: Callable[[Dict[str, Any]], None]) -> None:
        if listener not in self._patch_listeners:
            self._patch_listeners.append(listener)

    def unregister_patch_listener(self, listener: Callable[[Dict[str, Any]], None]) -> None:
        if listener in self._patch_listeners:
            self._patch_listeners.remove(listener)

    def register_update_listener(self, listener: Callable[[str, CanonicalQuote], None]) -> None:
        if listener not in self._update_listeners:
            self._update_listeners.append(listener)

    def unregister_update_listener(self, listener: Callable[[str, CanonicalQuote], None]) -> None:
        if listener in self._update_listeners:
            self._update_listeners.remove(listener)

    def _on_provider_event(self, event_type: str, raw_data: Dict[str, Any], symbol: str) -> None:
        """
        Invoked on FastAPI event loop whenever provider receives a trade or bidask tick.
        Updates in-memory MarketState and broadcasts incremental patch.
        """
        try:
            if self._server_owned and self._event_session_date(raw_data) > reference_session_date().isoformat():
                # Do not let an early next-session reset erase the overnight close.
                return
            if event_type == "trade_print":
                # Polling providers can backfill confirmed exchange prints after the
                # batched board observation has already advanced quote state. Applying an
                # older print to MarketState would correctly be rejected as stale, but the
                # time-and-sales tape should still retain that real print. Keep this event
                # on its own path: it cannot mutate quote, analytics or live bars.
                quote = self.state.get_quote(symbol)
                printed = traded_log.record_provider_print(symbol, raw_data, quote=quote)
                if printed is not None:
                    asyncio.ensure_future(traded_log.persist(symbol, printed))
                    message = {
                        "type": "trade_print", "symbol": symbol,
                        "print": printed, "ts": printed["ts"],
                    }
                    for listener in self._patch_listeners:
                        try:
                            listener(message)
                        except Exception as err:  # noqa: BLE001
                            logger.warning("Error broadcasting confirmed trade print: %s", err)
                return
            if event_type == "trade":
                quote, diff = self.state.apply_trade_event(raw_data)
                # Time & sales. Provider-confirmed prints and deduplicated SSI latest-match
                # transitions print; the 20s board poll carries only a daily snapshot.
                if not raw_data.get("_synthetic_session_snapshot"):
                    try:
                        printed = traded_log.record(quote, diff, event=raw_data)
                        if printed is not None:
                            asyncio.ensure_future(traded_log.persist(quote.symbol, printed))
                            # Push the print on the same rail as quote and bar patches.
                            # Polling REST every 5s left the tape visibly behind STATS and
                            # the watchlist row, which update on every tick; a print is a
                            # tick, so it belongs on the tick path - for every subscribed
                            # symbol, not just whichever panel happens to be open.
                            print_msg = {
                                "type": "trade_print",
                                "symbol": quote.symbol,
                                "print": printed,
                                "ts": quote.received_timestamp,
                            }
                            for listener in self._patch_listeners:
                                try:
                                    listener(print_msg)
                                except Exception as err:  # noqa: BLE001
                                    logger.warning("Error broadcasting trade print: %s", err)
                    except Exception as err:  # noqa: BLE001 - the tape must never break the feed
                        logger.debug("Traded-log record failed for %s: %s", quote.symbol, err)
            else:
                quote, diff = self.state.apply_bidask_event(raw_data)

            if diff and self._patch_listeners:
                patch_obj = quote.to_wire_patch(diff)
                wire_msg = {
                    "type": "patch",
                    "symbol": quote.symbol,
                    "patch": patch_obj,
                    "ts": quote.received_timestamp,
                }
                for listener in self._patch_listeners:
                    try:
                        listener(wire_msg)
                    except Exception as err:
                        logger.warning(f"Error broadcasting patch to listener: {err}")

            if event_type == "trade" and self._patch_listeners:
                for bar_msg in live_bar_builder.on_trade(quote.symbol, raw_data):
                    for listener in self._patch_listeners:
                        try:
                            listener(bar_msg)
                        except Exception as err:
                            logger.warning("Error broadcasting bar patch: %s", err)

            # Non-blocking async warm cache persistence
            try:
                self.store.enqueue_save(quote.symbol, quote)
            except Exception as store_err:
                logger.debug(f"Store enqueue debug: {store_err}")

            if self._update_listeners:
                for u_listener in self._update_listeners:
                    try:
                        u_listener(quote.symbol, quote)
                    except Exception as u_err:
                        logger.warning(f"Error notifying state update listener: {u_err}")

            event_session = self._event_session_date(raw_data)
            self._schedule_reference_refresh(event_session)
        except Exception as e:
            logger.error(f"Error processing provider event ({event_type}): {e}")

    @staticmethod
    def _event_session_date(raw_data: Dict[str, Any]) -> str:
        for key in ("TradingDate", "Timestamp"):
            value = raw_data.get(key)
            if value:
                candidate = str(value).strip()[:10]
                if len(candidate) == 10 and candidate[4:5] == "-" and candidate[7:8] == "-":
                    return candidate
        return market_session.get_vn_now().date().isoformat()

    async def _refresh_reference_metadata(self, target_session: date) -> int:
        updates = await refresh_session_references(
            provider=self.provider,
            state=self.state,
            store=self.store,
            symbols=self.get_server_universe_symbols() or self.get_desired_symbols(),
            session_date=target_session,
        )
        for update in updates:
            if not self._patch_listeners:
                continue
            wire_msg = {
                "type": "patch",
                "symbol": update.symbol,
                "patch": update.quote.to_wire_patch(update.diff),
                "ts": update.quote.reference_timestamp,
            }
            for listener in self._patch_listeners:
                try:
                    listener(wire_msg)
                except Exception as err:
                    logger.warning("Error broadcasting reference patch to listener: %s", err)
        return len(updates)

    def _reference_metadata_complete(self, session_date: str) -> bool:
        """Whether every universe symbol has all the reference metadata THIS SOURCE
        (`provider.get_session_reference_data`) can actually supply.

        Ceiling/floor is excluded for CWs: the provider has no CW band endpoint, so those
        two fields can never arrive here — a CW's displayed bands come from the snapshot
        resolver deriving them from the underlying instead (`_derive_cw_bands`), a separate
        path this loop doesn't feed. Counting a structurally-unfillable field as "missing"
        would keep this retrying every `_REFERENCE_RETRY_COOLDOWN_SECONDS` forever, 24/7,
        hammering the provider for a universe that is one-third CWs.
        """
        symbols = self.get_server_universe_symbols() or self.get_desired_symbols()

        def complete(symbol: str) -> bool:
            quote = self.state.get_quote(symbol)
            if quote is None or quote.reference_session_date != session_date:
                return False
            fields = (
                ("reference_price",)
                if self.state.determine_instrument_type(symbol) == "CW"
                else ("reference_price", "ceiling_price", "floor_price")
            )
            return all(getattr(quote, field) is not None for field in fields)

        return bool(symbols) and all(complete(symbol) for symbol in symbols)

    async def _attempt_reference_refresh(self, target: date) -> None:
        session_date = target.isoformat()
        self._reference_attempt_session = session_date
        try:
            await self._refresh_reference_metadata(target)
        except Exception as exc:  # noqa: BLE001 - metadata must never stop the streams
            logger.warning("Session reference refresh failed: %s", exc)
        finally:
            if self._reference_metadata_complete(session_date):
                self._reference_refresh_session = session_date
                self._reference_retry_at = 0.0
            else:
                self._reference_refresh_session = None
                self._reference_retry_at = monotonic() + _REFERENCE_RETRY_COOLDOWN_SECONDS

    def _schedule_reference_refresh(self, session_date: str) -> None:
        """Retry incomplete metadata on later ticks, at most once per cooldown."""
        if self._reference_refresh_session == session_date:
            return
        if self._reference_refresh_task and not self._reference_refresh_task.done():
            return
        if self._reference_attempt_session == session_date and monotonic() < self._reference_retry_at:
            return
        try:
            target = date.fromisoformat(session_date)
            if target != reference_session_date():
                return
            loop = asyncio.get_running_loop()
        except (RuntimeError, ValueError):
            return

        self._reference_refresh_task = loop.create_task(self._attempt_reference_refresh(target))

    def _session_clock_tick(self) -> None:
        """Own 08:00 rollover and phase notifications even with no clients/provider ticks."""
        now = market_session.get_vn_now()
        target = reference_session_date(now).isoformat()
        for quote, diff in self.state.advance_display_session(target):
            self.store.enqueue_save(quote.symbol, quote)
            message = {"type": "patch", "symbol": quote.symbol,
                       "patch": quote.to_wire_patch(diff), "ts": int(now.timestamp() * 1000)}
            for listener in self._patch_listeners:
                try:
                    listener(message)
                except Exception:
                    logger.exception("Session rollover patch listener failed")
        self._schedule_reference_refresh(target)
        phase = (target, market_session.get_market_phase(now).value)
        if phase != self._last_clock_phase:
            self._last_clock_phase = phase
            self._notify_status_change()

    async def _run_session_clock(self) -> None:
        while True:
            try:
                self._session_clock_tick()
            except Exception:
                logger.exception("Market session clock failed; retrying")
            await asyncio.sleep(1)

    async def _run_session_trade_poll(self) -> None:
        """Seed the trade group (last price + session OHLC / volume / value) for universe
        symbols that have not received an observation yet this session — sparsely
        traded covered warrants otherwise show a live order book but no trade at all. A
        real stream tick always wins via ``apply_trade_event``'s stale-timestamp guard.
        """
        while True:
            try:
                if self._server_owned and market_session.is_trading_active():
                    await self._poll_session_trades()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Session trade poll failed; retrying")
            await asyncio.sleep(20)

    async def _poll_session_trades(self) -> None:
        symbols = self.get_server_universe_symbols()
        if not symbols:
            return
        target = reference_session_date()
        try:
            snapshot = await self.provider.get_session_trade_snapshot(symbols, target)
        except NotImplementedError:
            return
        except Exception as exc:  # noqa: BLE001 - the live streams must not depend on this
            logger.warning("Session trade snapshot unavailable: %s", exc)
            return
        target_iso = target.isoformat()
        for sym, values in snapshot.items():
            last = values.get("last_price")
            if last is None or last <= 0:
                continue
            as_of = str(values.get("as_of") or "").strip()
            ref = values.get("reference_price")
            event: Dict[str, Any] = {
                "Ticker": sym,
                "Close": last,
                "Open": values.get("open_price"),
                "High": values.get("high_price"),
                "Low": values.get("low_price"),
                "TotalMatchVolume": values.get("total_volume"),
                "TotalMatchValue": values.get("trading_value"),
                "TradingDate": as_of or f"{target_iso} 09:00",
                # Read from a daily bar, not an individual match: the traded log must not
                # print it, or the tape would fill with a phantom row every 20 seconds.
                "_synthetic_session_snapshot": True,
            }
            if as_of:
                event["Timestamp"] = as_of
            if ref is not None:
                event["Reference"] = ref
                event["Change"] = last - ref
            # Routes through apply_trade_event (session prep, stale guard, diff, broadcast).
            self._on_provider_event("trade", event, sym)

    def get_desired_symbols(self) -> List[str]:
        return sorted(list(self._desired_symbols))

    def get_active_symbols(self) -> List[str]:
        return sorted(list(self._active_symbols))

    def get_server_universe_symbols(self) -> List[str]:
        """Return the immutable configured realtime universe, regardless of feed state."""
        return sorted(self._server_universe_symbols)

    def is_in_server_universe(self, symbol: str) -> bool:
        return symbol.strip().upper() in self._server_universe_symbols

    def get_universe_health(self) -> Dict[str, Any]:
        configured = set(self._server_universe_symbols)
        active = set(self._active_symbols)
        return {
            **self._server_universe_health,
            "status": "OK" if self._server_universe_health.get("complete") else "DEGRADED",
            "active_size": len(active),
            "server_universe_size": len(configured),
            "active_complete": bool(configured) and active == configured,
            "inactive_symbols": sorted(configured - active),
        }

    def configure_server_universe(self, universe: "ResolvedResearchUniverse") -> TupleBoolStr:
        """Install the one product-owned upstream universe before provider startup.

        Once configured, legacy mutation methods reject changes.  Browser interest is
        managed solely by ``MarketConnectionManager`` and can never reach this method.
        """
        symbols = list(dict.fromkeys(s.strip().upper() for s in universe.symbols if s.strip()))
        health = universe.health()
        self._server_owned = True
        self._active_symbols.clear()
        self._reference_refresh_session = None
        self._reference_attempt_session = None
        self._reference_retry_at = 0.0
        if len(symbols) > self.max_symbols:
            health = {
                **health,
                "status": "DEGRADED",
                "complete": False,
                "issues": [
                    *health.get("issues", []),
                    {
                        "symbol": "__UNIVERSE__",
                        "reason": f"capacity_{self.max_symbols}_below_universe_{len(symbols)}",
                    },
                ],
            }
            self._server_universe_symbols = set()
            self._desired_symbols = set()
            self._server_universe_health = health
            return False, "Realtime universe exceeds provider capacity"

        self._server_universe_symbols = set(symbols)
        self._desired_symbols = set(symbols)
        self._server_universe_health = health
        return True, "Server realtime universe configured"

    def subscribe(self, symbols: List[str]) -> TupleBoolStr:
        """
        Adds symbols to desired subscription set.
        Enforces maximum capacity (rejects addition if union exceeds max_symbols).
        """
        if self._server_owned:
            return False, "Realtime subscriptions are owned by the server universe"

        clean = [s.strip().upper() for s in symbols if s.strip()]
        new_set = self._desired_symbols.union(clean)

        if len(new_set) > self.max_symbols:
            msg = f"Subscription count {len(new_set)} exceeds capacity limit {self.max_symbols}"
            logger.warning(msg)
            return False, msg

        if new_set != self._desired_symbols:
            self._desired_symbols = new_set
            self._schedule_debounced_restart()

        return True, "Subscribed successfully"

    def set_exact_subscriptions(self, symbols: List[str]) -> TupleBoolStr:
        """
        Replaces the desired subscription set with the exact provided symbols.
        Enforces maximum capacity (rejects if count exceeds max_symbols).
        """
        if self._server_owned:
            return False, "Realtime subscriptions are owned by the server universe"

        clean = list(dict.fromkeys([s.strip().upper() for s in symbols if s.strip()]))
        if len(clean) > self.max_symbols:
            msg = f"Subscription count {len(clean)} exceeds capacity limit {self.max_symbols}"
            logger.warning(msg)
            return False, msg

        new_set = set(clean)
        if new_set != self._desired_symbols:
            self._desired_symbols = new_set
            self._schedule_debounced_restart()

        return True, "Subscriptions set successfully"

    async def hydrate_missing_market_state(self, symbols: List[str]) -> List[str]:
        """
        Centralized warm-cache hydration. Loads cached quotes from MarketStateStore
        for any symbols missing from in-memory MarketState, validates trading-session
        freshness (Asia/Ho_Chi_Minh UTC+7), sanitizes previous-day session values, and merges
        accepted quotes into MarketState.

        Invariants:
        1. Stale-write prevention: restore_quote rejects if existing in-memory quote is newer.
        2. Session freshness: If cache timestamp belongs to a previous calendar day in VN time,
           session-specific fields (last_price, total_volume, bid1, ask1) are sanitized (set to None)
           so yesterday's trade/volume is never presented as today's live session state.
        3. Never promotes bid/ask midpoint to last_price.

        Returns the list of symbol names successfully restored.
        """
        clean_syms = [str(s).upper().strip() for s in symbols if str(s).strip()]
        if not clean_syms or not self.store.is_available():
            return []

        target_reference_session = reference_session_date().isoformat()
        candidates: List[str] = []
        for symbol in clean_syms:
            current = self.state.get_quote(symbol)
            if current is None or (
                current.reference_session_date != target_reference_session
                or any(
                    value is None
                    for value in (
                        current.reference_price,
                        current.ceiling_price,
                        current.floor_price,
                    )
                )
            ):
                candidates.append(symbol)
        if not candidates:
            return []

        restored_symbols: List[str] = []
        try:
            loaded = await self.store.load_many(candidates)
            if not loaded:
                return []

            now_vn = market_session.get_vn_now()
            display_day = reference_session_date(now_vn)

            for sym, quote in loaded.items():
                ts_ms = quote.received_timestamp or quote.source_timestamp
                if ts_ms:
                    quote_dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=VN_TZ)
                    is_same_session = (quote_dt.date() == display_day)
                else:
                    is_same_session = False

                reference_is_current = quote.reference_session_date == target_reference_session
                reference_update = {
                    "reference_price": quote.reference_price if reference_is_current else None,
                    "ceiling_price": quote.ceiling_price if reference_is_current else None,
                    "floor_price": quote.floor_price if reference_is_current else None,
                    "reference_session_date": (
                        quote.reference_session_date if reference_is_current else None
                    ),
                    "reference_timestamp": quote.reference_timestamp if reference_is_current else None,
                }

                if not is_same_session:
                    # Previous-session quote: sanitize intraday fields so they are not presented as today's session state
                    sanitized_quote = quote.model_copy(
                        update={
                            "last_price": None,
                            "open_price": None,
                            "high_price": None,
                            "low_price": None,
                            "average_price": None,
                            "price_change": None,
                            "price_change_percent": None,
                            "total_volume": None,
                            "trading_value": None,
                            "traded_quantity": None,
                            "bid1_price": None,
                            "bid1_quantity": None,
                            "ask1_price": None,
                            "ask1_quantity": None,
                            "bid2_price": None,
                            "bid2_quantity": None,
                            "ask2_price": None,
                            "ask2_quantity": None,
                            "bid3_price": None,
                            "bid3_quantity": None,
                            "ask3_price": None,
                            "ask3_quantity": None,
                            "underlying_price": None,
                            "iv_bid": None,
                            "iv_trade": None,
                            "iv_ask": None,
                            "provider_trading_date": None,
                            "provider_timestamp": None,
                            "source_timestamp": None,
                            "trade_timestamp": None,
                            "book_timestamp": None,
                            "trade_received_timestamp": None,
                            "book_received_timestamp": None,
                            "market_session_date": None,
                            **reference_update,
                        }
                    )
                else:
                    sanitized_quote = quote.model_copy(update=reference_update)

                existing = self.state.get_quote(sym)
                if existing is not None:
                    if existing.reference_session_date != target_reference_session:
                        self.state.apply_reference_metadata(
                            sym,
                            session_date=target_reference_session,
                            observed_timestamp=sanitized_quote.reference_timestamp,
                        )
                        existing = self.state.get_quote(sym) or existing
                    reference_values = {
                        "reference_price": (
                            sanitized_quote.reference_price
                            if existing.reference_price is None
                            else None
                        ),
                        "ceiling_price": (
                            sanitized_quote.ceiling_price
                            if existing.ceiling_price is None
                            else None
                        ),
                        "floor_price": (
                            sanitized_quote.floor_price
                            if existing.floor_price is None
                            else None
                        ),
                    }
                    if reference_is_current and any(
                        value is not None for value in reference_values.values()
                    ):
                        _merged, diff = self.state.apply_reference_metadata(
                            sym,
                            session_date=target_reference_session,
                            **reference_values,
                            observed_timestamp=max(
                                sanitized_quote.reference_timestamp or 0,
                                existing.reference_timestamp or 0,
                            ) or None,
                        )
                        if diff:
                            restored_symbols.append(sym)
                    continue

                if self.state.restore_quote(sanitized_quote):
                    restored_symbols.append(sym)
        except Exception as e:
            logger.warning(f"Error hydrating missing market state for {candidates}: {e}")

        return restored_symbols

    def unsubscribe(self, symbols: List[str]) -> None:
        """Removes symbols from desired subscription set."""
        if self._server_owned:
            return
        clean = [s.strip().upper() for s in symbols if s.strip()]
        new_set = self._desired_symbols.difference(clean)
        if new_set != self._desired_symbols:
            self._desired_symbols = new_set
            self._schedule_debounced_restart()

    def register_status_listener(self, listener: Callable[[], None]) -> None:
        if listener not in self._status_listeners:
            self._status_listeners.append(listener)

    def _notify_status_change(self) -> None:
        for listener in self._status_listeners:
            try:
                listener()
            except Exception as err:
                logger.warning(f"Error notifying status listener: {err}")

    def _schedule_debounced_restart(self) -> None:
        """Cancels any pending restart task and schedules a new debounced provider restart."""
        if self._debounce_task and not self._debounce_task.done():
            self._debounce_task.cancel()

        async def _do_restart():
            try:
                await asyncio.sleep(self.debounce_ms / 1000.0)
            except asyncio.CancelledError:
                # A newer watchlist change superseded this one before the debounce elapsed.
                # Nothing was started yet, so there is nothing to unwind.
                return

            target = sorted(list(self._desired_symbols))
            if set(target) == self._active_symbols:
                return

            logger.info(f"Applying debounced subscription change: {target}")
            await self._refresh_reference_metadata(reference_session_date())
            # Shield the actual stream restart: if this debounce task is cancelled mid-restart
            # (e.g. another watchlist change lands), the provider must still finish retiring the
            # old SignalR lifecycle and bringing the new one up atomically. The provider
            # serialises lifecycle transitions on its own lock, so the next restart simply waits.
            success = await asyncio.shield(self.provider.set_subscriptions(target))
            if success:
                self._active_symbols = set(target)
            self._notify_status_change()

        try:
            loop = asyncio.get_running_loop()
            self._debounce_task = loop.create_task(_do_restart())
        except RuntimeError:
            pass

    async def initialize(self) -> bool:
        """Initialize cache and activate the server universe before accepting clients."""
        try:
            await self.store.initialize()
        except Exception as e:
            logger.warning(f"Market state store initialization warning: {e}")

        target = self.get_server_universe_symbols()
        if target:
            await self.hydrate_missing_market_state(target)

        connected = await self.provider.connect()
        if not connected:
            self._active_symbols.clear()
            if self._server_owned and (self._session_clock_task is None or self._session_clock_task.done()):
                self._session_clock_task = asyncio.create_task(self._run_session_clock())
            self._notify_status_change()
            return False

        # Legacy standalone managers remain connect-only until their tests/internal
        # owners explicitly subscribe.  The application singleton is server-owned.
        if not self._server_owned:
            self._notify_status_change()
            return True

        if not target:
            logger.warning("Realtime universe is empty; provider connected without streams.")
            self._notify_status_change()
            return False

        await self._attempt_reference_refresh(reference_session_date())
        success = await self.provider.set_subscriptions(target)
        if success:
            self._active_symbols = set(target)
            logger.info("Activated server-owned realtime universe (%d symbols).", len(target))
        else:
            self._active_symbols.clear()
            logger.error("Provider rejected the server-owned realtime universe (%d symbols).", len(target))
        if self._session_clock_task is None or self._session_clock_task.done():
            self._session_clock_task = asyncio.create_task(self._run_session_clock())
        if self._session_trade_poll_task is None or self._session_trade_poll_task.done():
            self._session_trade_poll_task = asyncio.create_task(self._run_session_trade_poll())
        self._notify_status_change()
        return success

    async def shutdown(self) -> None:
        """Cleans up upstream streams and warm cache store on application shutdown."""
        if self._session_clock_task:
            self._session_clock_task.cancel()
            await asyncio.gather(self._session_clock_task, return_exceptions=True)
            self._session_clock_task = None
        if self._session_trade_poll_task:
            self._session_trade_poll_task.cancel()
            await asyncio.gather(self._session_trade_poll_task, return_exceptions=True)
            self._session_trade_poll_task = None
        if self._debounce_task and not self._debounce_task.done():
            self._debounce_task.cancel()
        if self._reference_refresh_task and not self._reference_refresh_task.done():
            self._reference_refresh_task.cancel()
            await asyncio.gather(self._reference_refresh_task, return_exceptions=True)
        try:
            await self.store.close()
        except Exception as e:
            logger.warning(f"Market state store shutdown warning: {e}")
        await self.provider.disconnect()
        self._active_symbols.clear()


# Global subscription coordinator instance
subscription_manager = SubscriptionManager()
