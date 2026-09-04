"""Bounded HTTP reads around the slow, polled FiinQuant market-wide overview."""

from __future__ import annotations

import asyncio
import copy
import logging
import math
import time
from datetime import datetime
from typing import Any, Callable

from app.market_data.market_session import market_session

logger = logging.getLogger(__name__)

# HOSE continuous session opens 09:00 ICT; mirrors the frontend's own SESSION_OPEN_MIN
# (market_overview_strip.tsx) and the provider's identical constant.
_SESSION_OPEN_MIN = 9 * 60


def _sparkline_settled(cache: dict[str, Any]) -> bool:
    """False if any index's chart is missing its early bars - a fetch that raced a
    FiinQuant hiccup and came back starting well after 09:00 ICT (confirmed live:
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

    def _ttl_seconds(self) -> float:
        """60s while trading is active; otherwise stretched to cover the whole closed
        stretch (lunch, evening, weekend, holiday) — the overview cannot change until the
        next session opens, so there is nothing new to fetch in the meantime.

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
            return max(60.0, float(self._seconds_to_next_session()))
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
        usable = bool(result.get("top_stock_volume") or result.get("top_cw_volume")) or any(
            item.get("value") is not None for item in result.get("indices", [])
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

    def _payload(self) -> dict[str, Any]:
        refreshing = self._refresh_task is not None and not self._refresh_task.done()
        if self._cache is None:
            return {
                "indices": [], "top_stock_volume": [], "top_cw_volume": [],
                "as_of": None, "source": "FIINQUANT", "availability": "UNAVAILABLE",
                "market_session_active": market_session.is_trading_active(),
                "market_phase": market_session.get_market_phase().value,
                "stock_scope": "HOSE (VNINDEX constituents)",
                "cw_scope": "active CW registry", "refreshing": refreshing,
            }
        result = copy.deepcopy(self._cache)
        age = max(0.0, time.time() - self._cached_at)
        ttl = self._ttl_seconds()
        stale = age >= ttl or bool(result.get("stale"))
        result.update({
            "refreshing": refreshing, "cache_age_seconds": round(age, 3),
            "market_session_active": market_session.is_trading_active(),
            "market_phase": market_session.get_market_phase().value,
        })
        if stale:
            result.update({"stale": True, "source": "FIINQUANT_CACHE", "availability": "PARTIAL"})
            for item in result.get("indices", []):
                item["stale"] = True
        return result

    async def get(self, symbols: list[str]) -> dict[str, Any]:
        if self._provider is None:
            from app.market_data.market_subscription_manager import subscription_manager
            self.configure(subscription_manager.provider, subscription_manager.store)
        await self._load()
        ttl = self._ttl_seconds()
        if self._cache is None or time.time() - self._cached_at >= ttl:
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
