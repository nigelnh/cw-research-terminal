"""Bounded HTTP reads around the slow, polled market-wide overview."""

from __future__ import annotations

import asyncio
import copy
import logging
import math
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

from app.market_data.market_session import market_session
from app.market_data.session_reference import reference_session_date
from app.market_data.trading_calendar import session_context

logger = logging.getLogger(__name__)

# HOSE continuous session opens 09:00 ICT; mirrors the frontend's own SESSION_OPEN_MIN
# (market_overview_strip.tsx) and the provider's identical constant.
_SESSION_OPEN_MIN = 9 * 60


def _sparkline_settled(cache: dict[str, Any]) -> bool:
    """False if any index's chart is missing its early bars - a fetch that raced a
    provider hiccup and came back starting well after 09:00 ICT (confirmed live:
    production served exactly this - a chart starting ~11:05 instead of 09:00 - frozen for
    the rest of the closed stretch once the off-session TTL stretch made it "settled" by
    the stock-leaders check alone). >20 min of slack covers a merely-late opening tick
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
        if first_minutes > _SESSION_OPEN_MIN + 20:
            return False
    return True


class MarketOverviewService:
    def __init__(self, cold_read_timeout: float = 2.0) -> None:
        self._cold_read_timeout = cold_read_timeout
        self._provider = None
        self._store = None
        self._cache: dict[str, Any] | None = None
        self._cached_at = 0.0
        self._loaded = False
        self._load_lock = asyncio.Lock()
        self._refresh_task: asyncio.Task | None = None
        self._retry_at = 0.0
        # Injectable for deterministic tests, mirrors the provider's own off-session TTL.
        self._seconds_to_next_session: Callable[[], float] = (
            market_session.seconds_until_next_trading_session
        )
        self._seconds_to_display_rollover: Callable[[], float] = (
            market_session.seconds_until_display_rollover
        )

    def _ttl_seconds(self) -> float:
        """60s while trading is active; otherwise stretched to cover the whole closed
        stretch (lunch, evening, weekend, holiday) — the overview cannot change until the
        next session opens, so there is nothing new to fetch in the meantime — but never
        past the 08:00 ICT display rollover, which is where the rest of the board moves to
        a new session.

        Except: if the cached payload still lacks stock leaders, or an index chart is
        missing its early bars (the provider's background sweep hadn't finished, or an
        intraday fetch hiccuped, when it was built), stay on the short TTL instead - a
        multi-day-stale panel for the rest of a closed weekend would otherwise never
        self-correct, since nothing re-asks the provider for it.
        """
        if market_session.is_trading_active():
            return 60.0
        settled = bool(self._cache) and (
            self._cache.get("components", {}).get("top_stock_volume") == "AVAILABLE"
        ) and _sparkline_settled(self._cache)
        if not settled:
            return 60.0
        try:
            # Never past the 08:00 display rollover - the same bound the provider's own
            # cache uses. This layer is the one that persists, so without the cap a
            # payload built yesterday afternoon survived a restart and was still being
            # served at 08:51 the next morning, an hour after the board had rolled.
            return max(0.0, min(
                float(self._seconds_to_next_session()),
                float(self._seconds_to_display_rollover()),
            ))
        except Exception:  # noqa: BLE001 - never let a calendar bug wedge the cache
            return 300.0

    def configure(self, provider, store) -> None:
        self._provider, self._store = provider, store
        self._cache = None
        self._cached_at = 0.0
        self._loaded = False
        self._retry_at = 0.0

    def start_refresh(self, symbols: list[str]) -> None:
        if self._refresh_task is not None and not self._refresh_task.done():
            return
        if time.monotonic() < self._retry_at:
            return
        self._refresh_task = asyncio.create_task(self._refresh(symbols))
        self._refresh_task.add_done_callback(self._refresh_done)

    def _refresh_done(self, task: asyncio.Task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            self._retry_at = time.monotonic() + 60
            logger.warning("Market overview background refresh unavailable: %s", type(exc).__name__)

    async def _load(self) -> None:
        if self._loaded:
            return
        async with self._load_lock:
            if self._loaded:
                return
            if self._store is not None:
                try:
                    saved = await self._store.load_market_overview()
                    if isinstance(saved, dict) and isinstance(saved.get("payload"), dict):
                        payload = saved["payload"]
                        cached_at = float(saved.get("cached_at") or 0)
                        if math.isfinite(cached_at) and all(
                            isinstance(payload.get(key), list)
                            for key in ("indices", "top_stock_volume", "top_cw_volume")
                        ):
                            self._cache = payload
                            self._cached_at = cached_at
                except Exception as exc:
                    logger.warning("Market overview restore unavailable: %s", type(exc).__name__)
            self._loaded = True

    async def _refresh(self, symbols: list[str]) -> None:
        await self._load()
        result = await self._provider.get_market_overview(symbols)
        # At the 08:00 display rollover Vnstock can confirm today's official index
        # references before the first index bar exists.  A reference-only overview is a
        # valid pre-open payload and must replace yesterday's completed-session cache.
        usable = bool(result.get("top_stock_volume") or result.get("top_cw_volume")) or any(
            item.get("value") is not None or item.get("reference") is not None
            for item in result.get("indices", [])
        )
        if not usable:
            self._retry_at = time.monotonic() + 60
            return
        self._cache = result
        self._cached_at = time.time()
        if usable and self._store is not None:
            await self._store.save_market_overview({
                "payload": result, "cached_at": self._cached_at,
            })

    @staticmethod
    def _payload_session(result: dict[str, Any]) -> str | None:
        """The session the cached cards actually describe, from their own provenance."""
        dates = [
            ((item.get("provenance") or {}).get("price") or {}).get("session_date")
            for item in result.get("indices", [])
        ]
        real = sorted(d for d in dates if d)
        return real[-1] if real else None

    def _payload(self) -> dict[str, Any]:
        result = self._session_payload()
        result["sessionContext"] = session_context()
        health = self._provider.get_health() if callable(getattr(self._provider, "get_health", None)) else {}
        result["feedStatus"] = health.get("feedStatus")
        return result

    def _session_payload(self) -> dict[str, Any]:
        refreshing = self._refresh_task is not None and not self._refresh_task.done()
        if self._cache is None:
            return self._empty_payload(refreshing)
        result = copy.deepcopy(self._cache)

        # Past the 08:00 rollover, a payload from an earlier session is not "stale data",
        # it is the WRONG DAY. Marking it stale and serving it anyway is what left index
        # cards reading VN30 1,963.01 from 2026-09-07 at 08:44 the next morning, beside a
        # watchlist that had already blanked - the board disagreeing with itself. Expiring
        # the cache faster cannot fix this: the refresh it triggers only replaces the
        # payload if the provider answers, so with the feed down the old cards persisted
        # indefinitely. The session it belongs to is what decides, not its age.
        payload_session = self._payload_session(result)
        display_session = reference_session_date().isoformat()
        # Validate every card and every leaderboard independently, including future or
        # undated legacy payloads. One fresh index cannot legitimize yesterday's peers.
        def day(item):
            price = (item.get("provenance") or {}).get("price") or {}
            return price.get("session_date") or item.get("session_date") or (item.get("as_of") or "")[:10]
        for key in ("indices", "top_stock_volume", "top_cw_volume"):
            result[key] = [item for item in result.get(key, []) if day(item) == display_session]
        for item in result["indices"]:
            for group, fields in {
                "breadth": ("advancing", "ceiling", "unchanged", "declining", "floor"),
                "totals": ("volume", "trading_value"),
            }.items():
                prov = (item.get("provenance") or {}).get(group)
                if not prov or prov.get("session_date") != display_session:
                    item.update({field: None for field in fields})
                    item["availability"] = "PARTIAL"
            item["sparkline"] = [p for p in item.get("sparkline", [])
                                 if isinstance(p, dict) and str(p.get("timestamp", ""))[:10] == display_session]
        if not any(result[key] for key in ("indices", "top_stock_volume", "top_cw_volume")):
            empty = self._empty_payload(refreshing)
            empty.update({
                "session_date": display_session,
                "previous_session_date": payload_session,
                "unavailable_reason": (
                    "Awaiting confirmed data for session " + display_session
                ),
            })
            return empty

        age = max(0.0, time.time() - self._cached_at)
        ttl = self._ttl_seconds()
        stale = age >= ttl or bool(result.get("stale"))
        result.update({
            "refreshing": refreshing, "cache_age_seconds": round(age, 3),
            "market_session_active": market_session.is_trading_active(),
            "market_phase": market_session.get_market_phase().value,
        })
        if stale:
            result.update({"stale": True, "source": "VNSTOCK_CACHE", "availability": "PARTIAL"})
            for item in result.get("indices", []):
                item["stale"] = True
        return result

    @staticmethod
    def _empty_payload(refreshing: bool) -> dict[str, Any]:
        return {
            "indices": [], "top_stock_volume": [], "top_cw_volume": [],
            "as_of": None, "source": "VNSTOCK", "availability": "UNAVAILABLE",
            "market_session_active": market_session.is_trading_active(),
            "market_phase": market_session.get_market_phase().value,
            "stock_scope": "HOSE (VNINDEX constituents)",
            "cw_scope": "active CW registry", "refreshing": refreshing,
        }

    async def get(self, symbols: list[str]) -> dict[str, Any]:
        if self._provider is None:
            from app.market_data.market_subscription_manager import subscription_manager
            self.configure(subscription_manager.provider, subscription_manager.store)
        await self._load()
        ttl = self._ttl_seconds()
        if self._cache is None or time.time() - self._cached_at >= ttl or self._payload_session(self._cache) != reference_session_date().isoformat():
            self.start_refresh(symbols)
        if self._cache is None and self._refresh_task is not None:
            try:
                await asyncio.wait_for(
                    asyncio.shield(self._refresh_task), timeout=self._cold_read_timeout,
                )
            except Exception:
                pass  # the shared refresh continues; no browser request waits indefinitely
        return self._payload()

    async def close(self) -> None:
        if self._refresh_task is not None and not self._refresh_task.done():
            self._refresh_task.cancel()
            await asyncio.gather(self._refresh_task, return_exceptions=True)


market_overview_service = MarketOverviewService()
