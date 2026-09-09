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
import math
from collections import deque
from datetime import datetime, time as dt_time, timedelta
from typing import Any, Deque, Dict, List, Optional

from app.core.config import settings
from app.market_data.market_schemas import CanonicalQuote
from app.market_data.trading_calendar import VN_TZ, reference_session_date, seconds_until_display_rollover

logger = logging.getLogger(__name__)

#: Bumped to v2 when the stored shape changed from one JSON blob to a Redis LIST. The
#: version is part of the key on purpose: a list operation against a leftover v1 string
#: fails with WRONGTYPE, which - being caught, as a cache fault must be - would have
#: silently disabled persistence until the old key's TTL expired. A new prefix means the
#: two shapes can never meet, and yesterday's keys simply age out.
KEY_PREFIX = "cw_research:traded_log:v3"
#: The tape is kept until this hour on the following day, matching the dashboard's own
#: 08:00 ICT data rollover.
ROLLOVER_HOUR_ICT = 8


def seconds_until_rollover(now: Optional[datetime] = None) -> int:
    """Seconds from ``now`` until the next 08:00 ICT. Always at least a minute."""
    return max(1, int(seconds_until_display_rollover(now)))


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
    def _key(symbol: str, session_date: str | None = None) -> str:
        return f"{KEY_PREFIX}:{symbol.strip().upper()}:{session_date or reference_session_date().isoformat()}"

    # ------------------------------------------------------------------ write
    def record(self, quote: CanonicalQuote, diff: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Append one match. Returns the entry, or None when this event was not a match.

        A trade frame that only restates session totals (no new match timestamp) must not
        produce a print, or every 20s poll would add a duplicate row.
        """
        if not any(k in diff for k in ("trade_timestamp", "traded_quantity", "total_volume")):
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

        if session != reference_session_date().isoformat():
            return None
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
            "side": classify_side(price, quote.bid1_price, quote.ask1_price)
                if quote.book_timestamp and 0 <= stamp_ms - quote.book_timestamp <= 180000 else None,
            "cumulative_volume": quote.total_volume,
            "session_date": session,
        }

        entry["id"] = "|".join(str(entry.get(k, "")) for k in ("session_date", "ts", "price", "volume", "cumulative_volume"))
        tape = self._log.setdefault(symbol, deque(maxlen=self._memory))
        # The same match can be re-delivered after a reconnect; never print it twice.
        if any(p.get("id") == entry["id"] for p in tape):
            return None
        tape.append(entry)
        return entry

    def record_provider_print(
        self,
        symbol: str,
        raw: Dict[str, Any],
        *,
        quote: Optional[CanonicalQuote] = None,
    ) -> Optional[Dict[str, Any]]:
        """Append one provider-confirmed print without mutating the latest quote.

        A polling board snapshot is never accepted here. The caller must supply the
        timestamp, matched quantity and price returned by the provider's trade-history
        endpoint. Dedup includes cumulative volume because KBS can publish multiple same-
        second, same-price and same-size matches after normalizing away subsecond digits.
        """
        sym = symbol.strip().upper()
        stamp = raw.get("Timestamp")
        try:
            dt = datetime.fromisoformat(str(stamp).strip().replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=VN_TZ)
            stamp_ms = int(dt.timestamp() * 1000)
        except (TypeError, ValueError, OverflowError):
            return None
        session = str(raw.get("TradingDate") or dt.astimezone(VN_TZ).date().isoformat())[:10]
        if session != reference_session_date().isoformat():
            return None
        try:
            price = float(raw.get("Close"))
            volume = int(float(raw.get("MatchVolume")))
        except (TypeError, ValueError):
            return None
        if not math.isfinite(price) or price <= 0 or volume <= 0:
            return None
        cumulative = raw.get("TotalMatchVolume")
        try:
            cumulative = int(float(cumulative)) if cumulative is not None else None
        except (TypeError, ValueError):
            cumulative = None
        ref = quote.reference_price if quote is not None else None
        change = raw.get("Change")
        try:
            change = float(change) if change is not None and math.isfinite(float(change)) else None
        except (TypeError, ValueError):
            change = None
        if change is None and ref not in (None, 0):
            change = price - float(ref)
        side_text = str(raw.get("Side") or "").strip().lower()
        side = "B" if side_text in ("b", "buy", "ato_buy", "atc_buy") else (
            "S" if side_text in ("s", "sell", "ato_sell", "atc_sell") else None
        )
        entry = {
            "ts": stamp_ms,
            "time": dt.astimezone(VN_TZ).strftime("%H:%M:%S"),
            "price": price,
            "change": change,
            "change_percent": change / ref if change is not None and ref not in (None, 0) else None,
            "volume": volume,
            "side": side,
            "side_basis": "PROVIDER",
            "cumulative_volume": cumulative,
            "session_date": session,
            "source": str(raw.get("_provider_source") or "PROVIDER_TAPE"),
        }
        entry["id"] = str(raw.get("TradeId") or "|".join(
            str(entry.get(k, "")) for k in (
                "session_date", "ts", "price", "volume", "cumulative_volume"
            )
        ))

        if self._session.get(sym) != session:
            previous = self._session.get(sym)
            self._session[sym] = session
            self._log[sym] = deque(maxlen=self._memory)
            if previous is not None:
                self._pending_resets.add(sym)
        tape = self._log.setdefault(sym, deque(maxlen=self._memory))
        if any(item.get("id") == entry["id"] for item in tape):
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
        key = self._key(symbol, entry["session_date"])
        try:
            if symbol in self._pending_resets:
                self._pending_resets.discard(symbol)
                # Session is part of the key; old and new writers cannot erase one another.
                pass
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

    async def persist_many(self, symbol: str, entries: List[Dict[str, Any]]) -> None:
        """Persist a bounded on-demand backfill in one Redis transaction."""
        if self._redis is None or not entries:
            return
        sym = symbol.strip().upper()
        session = str(entries[-1].get("session_date") or reference_session_date().isoformat())
        key = self._key(sym, session)
        try:
            pipe = self._redis.pipeline()
            pipe.rpush(key, *(json.dumps(entry) for entry in entries))
            pipe.ltrim(key, -self._max, -1)
            pipe.expire(key, seconds_until_rollover())
            await pipe.execute()
            self._persist_failed.discard(sym)
        except Exception as err:  # noqa: BLE001 - memory remains a valid bounded fallback
            if sym not in self._persist_failed:
                self._persist_failed.add(sym)
                logger.warning("Traded-log backfill persist failed for %s: %s", sym, err)

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
        today = reference_session_date().isoformat()
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
                if item.get("session_date") and item["session_date"] == today:
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
        day = reference_session_date().isoformat()
        items = [p for p in list(tape or []) if p.get("session_date") == day][-limit:][::-1]
        return {
            "symbol": sym,
            "session_date": day,
            "items": items,
            "count": len(items),
            "coverage": "OBSERVED_WINDOW",
            "retained_limit": self._max,
            "truncated": len(items) >= min(limit, self._max),
            # The exchange publishes no per-match aggressor flag; see classify_side.
            "side_basis": self._side_basis(items),
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

        today = reference_session_date().isoformat()
        items: List[Dict[str, Any]] = []
        for raw in raw_items:
            try:
                item = json.loads(raw)
            except (TypeError, ValueError):
                continue
            if item.get("session_date") != today:
                continue
            items.append(item)
        items.sort(key=lambda i: i.get("ts") or 0, reverse=True)
        return {
            "symbol": sym,
            "session_date": today,
            "items": items,
            "count": len(items),
            "coverage": "OBSERVED_WINDOW",
            "retained_limit": self._max,
            "truncated": len(items) >= min(limit, self._max),
            "side_basis": self._side_basis(items),
        }

    @staticmethod
    def _side_basis(items: List[Dict[str, Any]]) -> str:
        bases = {item.get("side_basis", "DERIVED_FROM_BOOK") for item in items}
        if bases == {"PROVIDER"}:
            return "PROVIDER"
        if len(bases) > 1:
            return "MIXED"
        return "DERIVED_FROM_BOOK"

    def tracked_symbols(self) -> List[str]:
        return sorted(self._log.keys())


traded_log = TradedLog()
