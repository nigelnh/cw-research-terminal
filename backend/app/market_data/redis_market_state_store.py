import asyncio
import json
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
import redis.asyncio as aioredis
from redis.exceptions import RedisError

from app.core.config import settings
from app.market_data.market_schemas import CanonicalQuote, HistoricalBar
from app.market_data.market_state_store import MarketStateStore

logger = logging.getLogger(__name__)


class RedisMarketStateStore(MarketStateStore):
    """
    Async Redis implementation of MarketStateStore (Warm Market State Cache).
    
    Architectural Contract:
    - Secondary warm cache only (L2); primary live state remains in MarketState (L1).
    - Stores CANONICAL backend units (Raw VND for stocks/CWs, Points for Index).
    - Keys use versioned namespace: cw_research:market_state:v1:{SYMBOL}.
    - Performs non-blocking coalesced writes to protect callback threads and event loops.
    - Gracefully degrades to LIVE_WITHOUT_WARM_CACHE if Redis is unreachable.
    """

    KEY_PREFIX = "cw_research:market_state:v1"
    HISTORY_PREFIX = "cw_research:dashboard_history:v1"
    OVERVIEW_KEY = "cw_research:market_overview:v2"

    def __init__(
        self,
        redis_url: Optional[str] = None,
        enabled: Optional[bool] = None,
        ttl_seconds: Optional[int] = None,
        max_staleness_seconds: Optional[int] = None,
        redis_client: Optional[Any] = None,
    ):
        self._redis_url = redis_url if redis_url is not None else settings.REDIS_URL
        self._enabled = enabled if enabled is not None else settings.REDIS_ENABLED
        self._ttl_seconds = ttl_seconds if ttl_seconds is not None else settings.MARKET_STATE_CACHE_TTL_SECONDS
        self._max_staleness_seconds = (
            max_staleness_seconds if max_staleness_seconds is not None else settings.MARKET_STATE_MAX_STALENESS_SECONDS
        )

        self._client: Optional[aioredis.Redis] = redis_client
        self._connected = False
        self._write_buffer: Dict[str, CanonicalQuote] = {}
        self._write_lock: Optional[asyncio.Lock] = None
        self._flush_event: Optional[asyncio.Event] = None
        self._flush_task: Optional[asyncio.Task] = None
        self._is_closing = False
        self._connectivity_failure_seen = False
        # Process-lifetime, payload-free counters. Successes count quotes;
        # errors count failed operations (or malformed restore entries).
        self._counters: Dict[str, int] = {
            "writes_succeeded": 0,
            "quotes_restored": 0,
            "write_errors": 0,
            "restore_errors": 0,
            "connection_restores": 0,
        }

    def _mark_connected(self) -> None:
        """Record recovery once for each observed connectivity failure."""
        if not self._connected and self._connectivity_failure_seen:
            self._counters["connection_restores"] += 1
        self._connected = True
        self._connectivity_failure_seen = False

    def _mark_disconnected(self) -> None:
        self._connected = False
        self._connectivity_failure_seen = True

    def _get_key(self, symbol: str) -> str:
        return f"{self.KEY_PREFIX}:{symbol.strip().upper()}"

    def is_available(self) -> bool:
        return self._enabled and self._connected and self._client is not None

    async def initialize(self) -> None:
        if not self._enabled:
            logger.info("Redis MarketStateStore is disabled by configuration.")
            return

        if self._write_lock is None:
            self._write_lock = asyncio.Lock()
        if self._flush_event is None:
            self._flush_event = asyncio.Event()

        if self._client is None:
            try:
                self._client = aioredis.from_url(
                    self._redis_url,
                    decode_responses=True,
                    socket_connect_timeout=1.5,
                    socket_timeout=2.0,
                )
            except Exception as e:
                logger.warning("Failed to create Redis warm-cache client: %s", e)
                self._mark_disconnected()
                return

        # Verify connectivity via ping
        try:
            await self._client.ping()
            self._mark_connected()
            # Connection URLs commonly embed credentials. Never put the configured
            # endpoint in application logs, even at info level.
            logger.info("Connected to Redis Warm Market State Cache.")
        except (RedisError, OSError, Exception) as ping_err:
            logger.warning(f"Redis warm cache unavailable on startup ({ping_err}). Running in LIVE_WITHOUT_WARM_CACHE mode.")
            self._mark_disconnected()

        # Start coalesced background flush worker
        if self._flush_task is None or self._flush_task.done():
            self._is_closing = False
            self._flush_task = asyncio.create_task(self._flush_worker())

    async def close(self) -> None:
        self._is_closing = True
        if self._flush_event:
            self._flush_event.set()

        if self._flush_task and not self._flush_task.done():
            try:
                await asyncio.wait_for(self._flush_task, timeout=2.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._flush_task.cancel()

        # Final synchronous flush if client connected
        if self.is_available() and self._write_buffer:
            try:
                await self._drain_and_save()
            except Exception as e:
                logger.warning(f"Error during final Redis flush: {e}")

        if self._client:
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = None

        self._connected = False
        logger.info("Redis MarketStateStore closed.")

    def _is_quote_fresh(self, quote: CanonicalQuote) -> bool:
        """Validates that a quote's timestamp is within the acceptable max_staleness_seconds window."""
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        reference_ts = max(
            quote.received_timestamp or 0,
            quote.source_timestamp or 0,
            quote.reference_timestamp or 0,
        )
        if not reference_ts:
            return False
        age_seconds = (now_ms - reference_ts) / 1000.0
        return age_seconds <= self._max_staleness_seconds

    async def load(self, symbol: str) -> Optional[CanonicalQuote]:
        if not self.is_available() or self._client is None:
            return None

        key = self._get_key(symbol)
        try:
            raw = await self._client.get(key)
        except Exception as e:
            self._counters["restore_errors"] += 1
            logger.warning(f"Error loading {symbol} from Redis warm cache: {e}")
            self._mark_disconnected()
            return None

        if not raw:
            return None
        try:
            quote = CanonicalQuote.model_validate_json(raw)
            if not self._is_quote_fresh(quote):
                logger.debug(f"Cached quote for {symbol} rejected due to staleness.")
                return None
            self._counters["quotes_restored"] += 1
            return quote
        except Exception as e:
            self._counters["restore_errors"] += 1
            logger.warning(f"Malformed quote JSON in Redis for {symbol}: {e}")
            return None

    async def load_many(self, symbols: List[str]) -> Dict[str, CanonicalQuote]:
        if not self.is_available() or not symbols or self._client is None:
            return {}

        clean_syms = list(dict.fromkeys(s.strip().upper() for s in symbols if s.strip()))
        keys = [self._get_key(s) for s in clean_syms]

        try:
            results = await self._client.mget(keys)
            loaded: Dict[str, CanonicalQuote] = {}
            for sym, raw in zip(clean_syms, results):
                if raw:
                    try:
                        quote = CanonicalQuote.model_validate_json(raw)
                        if self._is_quote_fresh(quote):
                            loaded[sym] = quote
                        else:
                            logger.debug(f"Cached quote for {sym} rejected due to staleness.")
                    except Exception as parse_err:
                        self._counters["restore_errors"] += 1
                        logger.warning(f"Malformed quote JSON in Redis for {sym}: {parse_err}")
            # Count returned symbols rather than Redis rows so duplicate inputs are
            # not reported as multiple restores.
            self._counters["quotes_restored"] += len(loaded)
            return loaded
        except Exception as e:
            self._counters["restore_errors"] += 1
            logger.warning(f"Error loading symbols {clean_syms} from Redis: {e}")
            self._mark_disconnected()
            return {}

    async def save(self, symbol: str, quote: CanonicalQuote) -> None:
        if not self.is_available() or self._client is None:
            return

        key = self._get_key(symbol)
        try:
            raw_json = quote.model_dump_json()
        except Exception as e:
            self._counters["write_errors"] += 1
            logger.warning(f"Failed to serialize {symbol} for Redis warm cache: {e}")
            return

        try:
            await self._client.set(key, raw_json, ex=self._ttl_seconds)
            self._counters["writes_succeeded"] += 1
        except Exception as e:
            self._counters["write_errors"] += 1
            logger.warning(f"Failed to save {symbol} to Redis warm cache: {e}")
            self._mark_disconnected()

    async def save_many(self, quotes: Dict[str, CanonicalQuote]) -> None:
        if not self.is_available() or not quotes or self._client is None:
            return

        try:
            serialized = [
                (self._get_key(sym), quote.model_dump_json())
                for sym, quote in quotes.items()
            ]
        except Exception as e:
            self._counters["write_errors"] += 1
            logger.warning(f"Failed to serialize Redis batch of {len(quotes)} quotes: {e}")
            return

        try:
            pipe = self._client.pipeline()
            for key, raw_json in serialized:
                pipe.set(key, raw_json, ex=self._ttl_seconds)
            await pipe.execute()
            self._counters["writes_succeeded"] += len(quotes)
        except Exception as e:
            self._counters["write_errors"] += 1
            logger.warning(f"Failed to save batch of {len(quotes)} quotes to Redis: {e}")
            self._mark_disconnected()

    async def load_dashboard_history(
        self, symbol: str, price_basis: str, session_date: str
    ) -> Optional[List[HistoricalBar]]:
        if not self.is_available() or self._client is None:
            return None
        key = f"{self.HISTORY_PREFIX}:{symbol.strip().upper()}:{price_basis}:{session_date}"
        try:
            raw = await self._client.get(key)
            if not raw:
                return None
            bars = [HistoricalBar.model_validate(item) for item in json.loads(raw)]
            if any(
                bar.price_basis != price_basis
                or (bar.session_date or bar.date[:10]) > session_date
                for bar in bars
            ):
                return None
            return bars
        except Exception as exc:
            logger.warning("Dashboard history cache read failed for %s: %s", symbol, type(exc).__name__)
            return None

    async def save_dashboard_history(
        self, symbol: str, price_basis: str, session_date: str, bars: List[HistoricalBar]
    ) -> None:
        if not bars or not self.is_available() or self._client is None:
            return
        key = f"{self.HISTORY_PREFIX}:{symbol.strip().upper()}:{price_basis}:{session_date}"
        try:
            await self._client.set(
                key,
                json.dumps([bar.model_dump(mode="json") for bar in bars]),
                ex=max(1, int(settings.DASHBOARD_HISTORY_CACHE_TTL_SECONDS)),
            )
        except Exception as exc:
            logger.warning("Dashboard history cache write failed for %s: %s", symbol, type(exc).__name__)

    async def load_market_overview(self) -> Optional[Dict[str, Any]]:
        if not self.is_available() or self._client is None:
            return None
        try:
            raw = await self._client.get(self.OVERVIEW_KEY)
            return json.loads(raw) if raw else None
        except Exception as exc:
            logger.warning("Market overview cache read failed: %s", type(exc).__name__)
            return None

    async def save_market_overview(self, payload: Dict[str, Any]) -> None:
        if not self.is_available() or self._client is None:
            return
        try:
            await self._client.set(self.OVERVIEW_KEY, json.dumps(payload), ex=7 * 86400)
        except Exception as exc:
            logger.warning("Market overview cache write failed: %s", type(exc).__name__)

    def enqueue_save(self, symbol: str, quote: CanonicalQuote) -> None:
        """Buffers quote for asynchronous batch writing without blocking."""
        if not self._enabled:
            return

        sym = symbol.strip().upper()
        self._write_buffer[sym] = quote
        if self._flush_event:
            self._flush_event.set()

    async def _drain_and_save(self) -> None:
        if not self._write_buffer:
            return

        to_save: Dict[str, CanonicalQuote] = {}
        if self._write_lock:
            async with self._write_lock:
                to_save = dict(self._write_buffer)
                self._write_buffer.clear()
        else:
            to_save = dict(self._write_buffer)
            self._write_buffer.clear()

        if to_save:
            await self.save_many(to_save)

    async def _flush_worker(self) -> None:
        """Background coroutine coalescing incoming quote updates into pipelined Redis writes."""
        while not self._is_closing:
            try:
                if self._flush_event:
                    try:
                        await asyncio.wait_for(self._flush_event.wait(), timeout=0.2)
                        self._flush_event.clear()
                    except asyncio.TimeoutError:
                        pass

                if self._write_buffer and self.is_available():
                    await self._drain_and_save()
                elif not self._connected and self._enabled and self._client:
                    # Periodically attempt reconnect health check
                    try:
                        await self._client.ping()
                        self._mark_connected()
                        logger.info("Redis warm cache connection restored.")
                    except Exception:
                        self._mark_disconnected()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Redis flush worker iteration exception: {e}")
                await asyncio.sleep(0.5)

    async def delete(self, symbol: str) -> None:
        if not self.is_available() or self._client is None:
            return
        key = self._get_key(symbol)
        try:
            await self._client.delete(key)
        except Exception as e:
            logger.warning(f"Failed to delete {symbol} from Redis: {e}")

    async def health(self) -> Dict[str, Any]:
        """Sanitized diagnostics with a copy of process-lifetime counters."""
        connected = False
        if self._enabled and self._client:
            try:
                await self._client.ping()
                connected = True
                self._mark_connected()
            except Exception:
                connected = False
                self._mark_disconnected()

        return {
            "redis_enabled": self._enabled,
            "redis_connected": connected,
            "market_cache_available": self._enabled and connected,
            "key_prefix": self.KEY_PREFIX,
            "ttl_seconds": self._ttl_seconds,
            "max_staleness_seconds": self._max_staleness_seconds,
            "pending_write_buffer_size": len(self._write_buffer),
            "counters": dict(self._counters),
        }
