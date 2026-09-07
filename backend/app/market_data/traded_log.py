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

KEY_PREFIX = "cw_research:traded_log:v1"
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
    """Bounded in-memory tape per symbol, mirrored to Redis for restart survival."""

    def __init__(self, max_entries: Optional[int] = None) -> None:
        self._max = int(max_entries if max_entries is not None else settings.TRADED_LOG_MAX_ENTRIES)
        self._log: Dict[str, Deque[Dict[str, Any]]] = {}
        self._session: Dict[str, str] = {}
        self._redis: Any = None

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
            self._session[symbol] = session
            self._log[symbol] = deque(maxlen=self._max)

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

        tape = self._log.setdefault(symbol, deque(maxlen=self._max))
        # The same match can be re-delivered after a reconnect; never print it twice.
        if tape and tape[-1]["ts"] == entry["ts"] and tape[-1]["price"] == entry["price"]:
            return None
        tape.append(entry)
        return entry

    async def persist(self, symbol: str) -> None:
        """Mirror one symbol's tape to Redis. Never raises: the tape is a convenience."""
        if self._redis is None:
            return
        symbol = symbol.upper()
        tape = self._log.get(symbol)
        if not tape:
            return
        try:
            payload = json.dumps({"session_date": self._session.get(symbol), "items": list(tape)})
            await self._redis.set(self._key(symbol), payload, ex=seconds_until_rollover())
        except Exception as err:  # noqa: BLE001 - a cache fault must never break the feed
            logger.debug("Traded-log persist failed for %s: %s", symbol, err)

    async def restore(self, symbols: List[str]) -> int:
        """Reload tapes after a restart, dropping anything from an earlier session."""
        if self._redis is None or not symbols:
            return 0
        today = datetime.now(VN_TZ).date().isoformat()
        restored = 0
        for symbol in symbols:
            sym = symbol.upper()
            try:
                raw = await self._redis.get(self._key(sym))
            except Exception:  # noqa: BLE001
                continue
            if not raw:
                continue
            try:
                data = json.loads(raw)
                session = data.get("session_date")
                items = data.get("items") or []
            except (TypeError, ValueError):
                continue
            # Keep the previous session's tape until the 08:00 rollover retires the key.
            if not items or not session or session > today:
                continue
            self._session[sym] = session
            self._log[sym] = deque(items[-self._max:], maxlen=self._max)
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

    def tracked_symbols(self) -> List[str]:
        return sorted(self._log.keys())


traded_log = TradedLog()
