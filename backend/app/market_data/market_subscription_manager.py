import asyncio
import logging
from datetime import datetime
from typing import Set, List, Dict, Any, Callable, Optional, Tuple

from app.core.config import settings
from app.market_data.market_session import market_session, VN_TZ
from app.market_data.market_state import MarketState, market_state
from app.market_data.market_schemas import CanonicalQuote
from app.market_data.market_state_store import MarketStateStore, NullMarketStateStore
from app.market_data.redis_market_state_store import RedisMarketStateStore
from app.market_data.providers.base_market_provider import MarketDataProvider
from app.market_data.providers.fiinquant_provider import FiinQuantProvider

logger = logging.getLogger(__name__)

TupleBoolStr = Tuple[bool, str]

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
        self.max_symbols = max_symbols or settings.FIINQUANT_MAX_REALTIME_SYMBOLS
        self.debounce_ms = debounce_ms if debounce_ms is not None else settings.FIINQUANT_DEBOUNCE_MS

        self.provider = provider or FiinQuantProvider(max_symbols=self.max_symbols)

        self._desired_symbols: Set[str] = set()
        self._active_symbols: Set[str] = set()
        self._debounce_task: Optional[asyncio.Task] = None
        self._patch_listeners: List[Callable[[Dict[str, Any]], None]] = []
        self._status_listeners: List[Callable[[], None]] = []
        self._update_listeners: List[Callable[[str, CanonicalQuote], None]] = []

        # Register provider event callback
        self.provider.set_event_callback(self._on_provider_event)

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
            if event_type == "trade":
                quote, diff = self.state.apply_trade_event(raw_data)
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
        except Exception as e:
            logger.error(f"Error processing provider event ({event_type}): {e}")

    def get_desired_symbols(self) -> List[str]:
        return sorted(list(self._desired_symbols))

    def get_active_symbols(self) -> List[str]:
        return sorted(list(self._active_symbols))

    def subscribe(self, symbols: List[str]) -> TupleBoolStr:
        """
        Adds symbols to desired subscription set.
        Enforces maximum capacity (rejects addition if union exceeds max_symbols).
        """
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

        missing_syms = [s for s in clean_syms if not self.state.has_quote(s)]
        if not missing_syms:
            return []

        restored_symbols: List[str] = []
        try:
            loaded = await self.store.load_many(missing_syms)
            if not loaded:
                return []

            today_vn = market_session.get_vn_now().date()

            for sym, quote in loaded.items():
                ts_ms = quote.received_timestamp or quote.source_timestamp
                if ts_ms:
                    quote_dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=VN_TZ)
                    is_same_session = (quote_dt.date() == today_vn)
                else:
                    is_same_session = False

                if not is_same_session:
                    # Previous-session quote: sanitize intraday fields so they are not presented as today's session state
                    sanitized_quote = quote.model_copy(
                        update={
                            "last_price": None,
                            "price_change": None,
                            "price_change_percent": None,
                            "total_volume": None,
                            "bid1_price": None,
                            "bid1_volume": None,
                            "ask1_price": None,
                            "ask1_volume": None,
                        }
                    )
                else:
                    sanitized_quote = quote

                if self.state.restore_quote(sanitized_quote):
                    restored_symbols.append(sym)
        except Exception as e:
            logger.warning(f"Error hydrating missing market state for {missing_syms}: {e}")

        return restored_symbols

    def unsubscribe(self, symbols: List[str]) -> None:
        """Removes symbols from desired subscription set."""
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
        """Initializes secondary warm cache and upstream connection on application startup."""
        try:
            await self.store.initialize()
        except Exception as e:
            logger.warning(f"Market state store initialization warning: {e}")
        return await self.provider.connect()

    async def shutdown(self) -> None:
        """Cleans up upstream streams and warm cache store on application shutdown."""
        if self._debounce_task and not self._debounce_task.done():
            self._debounce_task.cancel()
        try:
            await self.store.close()
        except Exception as e:
            logger.warning(f"Market state store shutdown warning: {e}")
        await self.provider.disconnect()


# Global subscription coordinator instance
subscription_manager = SubscriptionManager()
