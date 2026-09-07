"""Per-symbol traded log (time & sales) for the instrument panel.

Every match observed on the trade stream is appended to a bounded, newest-first log that
survives a backend restart and is kept until 08:00 ICT the morning after its session - the
same rollover the dashboard already uses - so the panel still has the day's tape after the
close, not just while the market is open.

Two honesty constraints shape this module:

* Only REAL matches are recorded. The 20s session-trade poll also routes through the trade
  path, but it reads a daily bar and carries no individual match; those events are marked
  synthetic by the caller and skipped, or the tape would fill with phantom prints.

* The exchange does not tell us who was the aggressor. `Trading_Data_Stream` has no
  per-match buy/sell flag (`Bu`/`Sd` are market-wide totals), so the side is DERIVED with
  the standard quote rule against the last known book and is reported as `side_basis:
  "DERIVED_FROM_BOOK"`. A print inside the spread stays unclassified rather than guessed.
"""
from __future__ import annotations

import json
import logging
from collections import deque
from datetime import datetime, time as dt_time, timedelta
from typing import Any, Deque, Dict, List, Optional

from app.core.config import settings
from app.market_data.market_schemas import CanonicalQuote
from app.market_data.trading_calendar import VN_TZ

logger = logging.getLogger(__name__)

#: Bumped to v2 when the stored shape changed from one JSON blob to a Redis LIST. The
#: version is part of the key on purpose: a list operation against a leftover v1 string
#: fails with WRONGTYPE, which - being caught, as a cache fault must be - would have
#: silently disabled persistence until the old key's TTL expired. A new prefix means the
#: two shapes can never meet, and yesterday's keys simply age out.
KEY_PREFIX = "cw_research:traded_log:v2"
#: The tape is kept until this hour on the following day, matching the dashboard's own
#: 08:00 ICT data rollover.
ROLLOVER_HOUR_ICT = 8


def seconds_until_rollover(now: Optional[datetime] = None) -> int:
    """Seconds from ``now`` until the next 08:00 ICT. Always at least a minute."""
    current = (now or datetime.now(VN_TZ)).astimezone(VN_TZ)
    target = current.replace(hour=ROLLOVER_HOUR_ICT, minute=0, second=0, microsecond=0)
    if current >= target:
        target = target + timedelta(days=1)
    return max(60, int((target - current).total_seconds()))


def classify_side(price: float, bid: Optional[float], ask: Optional[float]) -> Optional[str]:
    """Aggressor side by the quote rule, or None when the book cannot settle it.

    At or above the ask the buyer crossed; at or below the bid the seller did. A print
    strictly inside the spread is genuinely ambiguous and is left blank - the alternative
    would be inventing a side the exchange never published.
    """
    if ask is not None and ask > 0 and price >= ask:
        return "B"
    if bid is not None and bid > 0 and price <= bid:
        return "S"
    return None


class TradedLog:
    """The session tape: a full session in Redis, a recent window in memory.

    The two bounds are deliberately different. Redis holds the whole session because it is
    the SHARED copy - every browser on every machine reads the same tape, so a second laptop
    opening at 14:00 gets the morning's prints it was never connected for. Memory holds only
    a recent window, because a full session for every watched symbol would cost around
    100MB on a single-replica container to cache history that is one Redis read away.
    """

    def __init__(
        self,
        max_entries: Optional[int] = None,
        memory_entries: Optional[int] = None,
    ) -> None:
        self._max = int(max_entries if max_entries is not None else settings.TRADED_LOG_MAX_ENTRIES)
        memory = int(
            memory_entries if memory_entries is not None else settings.TRADED_LOG_MEMORY_ENTRIES
        )
        # Caching more than is retained would be pointless, and a test that passes only
        # `max_entries` expects that to be the whole bound.
        self._memory = max(1, min(memory, self._max))
        self._log: Dict[str, Deque[Dict[str, Any]]] = {}
        self._session: Dict[str, str] = {}
        self._redis: Any = None
        # Symbols whose stored tape must be dropped before the next append.
        self._pending_resets: set[str] = set()
        # Symbols already warned about, so a Redis outage logs once rather than per tick.
        self._persist_failed: set[str] = set()

    def set_redis(self, client: Any) -> None:
        """Attach an already-connected client. Redis is optional: without it the tape is
        still served from memory and only loses history across a restart."""
        self._redis = client

    @staticmethod
    def _key(symbol: str) -> str:
        return f"{KEY_PREFIX}:{symbol.strip().upper()}"

    # ------------------------------------------------------------------ write
    def record(self, quote: CanonicalQuote, diff: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Append one match. Returns the entry, or None when this event was not a match.

        A trade frame that only restates session totals (no new match timestamp) must not
        produce a print, or every 20s poll would add a duplicate row.
        """
        if "trade_timestamp" not in diff:
            return None
        price = quote.last_price
        if price is None or price <= 0:
            return None
        stamp_ms = quote.trade_timestamp or quote.source_timestamp
        if stamp_ms is None:
            return None

        symbol = quote.symbol.upper()
        session = quote.market_session_date or datetime.fromtimestamp(
            stamp_ms / 1000.0, tz=VN_TZ
        ).date().isoformat()

        # A new session starts a fresh tape; yesterday's prints never blend into today's.
        if self._session.get(symbol) != session:
            previous = self._session.get(symbol)
            self._session[symbol] = session
            self._log[symbol] = deque(maxlen=self._memory)
            if previous is not None:
                self._pending_resets.add(symbol)

        # Change is versus the session reference by definition, so derive it when the frame
        # omits `Change` rather than leaving the column blank on an otherwise good print.
        ref = quote.reference_price
        change = quote.price_change
        change_pct = quote.price_change_percent
        if change is None and ref is not None and ref > 0:
            change = price - ref
        if change_pct is None and ref is not None and ref > 0:
            change_pct = (price - ref) / ref

        entry = {
            "ts": stamp_ms,
            "time": datetime.fromtimestamp(stamp_ms / 1000.0, tz=VN_TZ).strftime("%H:%M:%S"),
            "price": price,
            "change": change,
            "change_percent": change_pct,
            "volume": diff.get("traded_quantity", quote.traded_quantity),
            "side": classify_side(price, quote.bid1_price, quote.ask1_price),
            "session_date": session,
        }

        tape = self._log.setdefault(symbol, deque(maxlen=self._memory))
        # The same match can be re-delivered after a reconnect; never print it twice.
        if tape and tape[-1]["ts"] == entry["ts"] and tape[-1]["price"] == entry["price"]:
            return None
        tape.append(entry)
        return entry

    async def persist(self, symbol: str, entry: Dict[str, Any]) -> None:
        """Append ONE print to the symbol's Redis list. Never raises.

        A Redis LIST, not a JSON blob. The blob version re-serialised the entire tape on
        every print, which is fine at 200 entries and ruinous at session length - HPG
        prints roughly 24 times a minute, so a full-session tape would have meant rewriting
        about a megabyte per second. RPUSH + LTRIM is constant work per print regardless of
        how much history is retained, which is what makes keeping the whole session
        affordable in the first place.
        """
        if self._redis is None:
            return
        symbol = symbol.upper()
        key = self._key(symbol)
        try:
            if symbol in self._pending_resets:
                self._pending_resets.discard(symbol)
                await self._redis.delete(key)
            pipe = self._redis.pipeline()
            pipe.rpush(key, json.dumps(entry))
            # Bound the stored tape the same way the in-memory deque is bounded.
            pipe.ltrim(key, -self._max, -1)
            pipe.expire(key, seconds_until_rollover())
            await pipe.execute()
            self._persist_failed.discard(symbol)
        except Exception as err:  # noqa: BLE001 - a cache fault must never break the feed
            # Debug-only logging here once hid a dead persistence path for hours. The first
            # failure per symbol is worth a warning; the rest stay quiet so a Redis outage
            # cannot flood the log at tick rate.
            if symbol in self._persist_failed:
                logger.debug("Traded-log persist failed for %s: %s", symbol, err)
            else:
                self._persist_failed.add(symbol)
                logger.warning("Traded-log persist failed for %s: %s", symbol, err)

    async def _reset_redis_session(self, symbol: str) -> None:
        """Drop a symbol's stored tape when its session rolls over, so yesterday's prints
        cannot reappear under today's date."""
        if self._redis is None:
            return
        try:
            await self._redis.delete(self._key(symbol.upper()))
        except Exception as err:  # noqa: BLE001
            logger.debug("Traded-log reset failed for %s: %s", symbol, err)

    async def restore(self, symbols: List[str]) -> int:
        """Reload tapes after a restart so a redeploy does not erase the session.

        This is what makes the tape shared rather than per-browser: every client reads the
        same server-side history, and a second machine opening mid-session sees everything
        that has printed, not just what has arrived since it connected.
        """
        if self._redis is None or not symbols:
            return 0
        today = datetime.now(VN_TZ).date().isoformat()
        restored = 0
        for symbol in symbols:
            sym = symbol.upper()
            try:
                raw_items = await self._redis.lrange(self._key(sym), -self._memory, -1)
            except Exception:  # noqa: BLE001
                continue
            if not raw_items:
                continue
            items: List[Dict[str, Any]] = []
            for raw in raw_items:
                try:
                    item = json.loads(raw)
                except (TypeError, ValueError):
                    continue
                # A key surviving past the rollover would otherwise blend sessions.
                if item.get("session_date") and item["session_date"] <= today:
                    items.append(item)
            if not items:
                continue
            items.sort(key=lambda i: i.get("ts") or 0)
            self._session[sym] = items[-1].get("session_date")
            self._log[sym] = deque(items, maxlen=self._memory)
            restored += 1
        return restored

    # ------------------------------------------------------------------- read
    def get(self, symbol: str, limit: int = 50) -> Dict[str, Any]:
        """Newest-first prints for one symbol."""
        sym = symbol.strip().upper()
        tape = self._log.get(sym)
        items = list(tape)[-limit:][::-1] if tape else []
        return {
            "symbol": sym,
            "session_date": self._session.get(sym),
            "items": items,
            "count": len(items),
            # The exchange publishes no per-match aggressor flag; see classify_side.
            "side_basis": "DERIVED_FROM_BOOK",
        }

    async def get_session(self, symbol: str, limit: int = 100) -> Dict[str, Any]:
        """Newest-first prints, read from the SHARED tape so any machine sees the session.

        Serving this from process memory is what made the tape look empty on a second
        laptop: memory only ever holds a recent window, and before that a restart dropped it
        entirely. Redis is the copy every client shares, so it answers here and memory is
        the fallback for a Redis outage - which degrades to "recent prints only" rather
        than to nothing.
        """
        sym = symbol.strip().upper()
        if self._redis is None:
            return self.get(sym, limit=limit)
        try:
            raw_items = await self._redis.lrange(self._key(sym), -limit, -1)
        except Exception as err:  # noqa: BLE001
            logger.debug("Traded-log read failed for %s, serving memory: %s", sym, err)
            return self.get(sym, limit=limit)
        if not raw_items:
            # No stored tape yet (first prints of the session are still in flight, or Redis
            # was attached after the backend started); memory is the better answer.
            return self.get(sym, limit=limit)

        today = datetime.now(VN_TZ).date().isoformat()
        items: List[Dict[str, Any]] = []
        for raw in raw_items:
            try:
                item = json.loads(raw)
            except (TypeError, ValueError):
                continue
            if item.get("session_date") and item["session_date"] > today:
                continue
            items.append(item)
        items.sort(key=lambda i: i.get("ts") or 0, reverse=True)
        return {
            "symbol": sym,
            "session_date": (items[0].get("session_date") if items else None)
            or self._session.get(sym),
            "items": items,
            "count": len(items),
            "side_basis": "DERIVED_FROM_BOOK",
        }

    def tracked_symbols(self) -> List[str]:
        return sorted(self._log.keys())


traded_log = TradedLog()
