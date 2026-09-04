"""
Historical Volatility Service.

Maintains an in-memory cache of annualized historical volatility (HV) per UNDERLYING
equity symbol, computed from adjusted daily closes. This is the independent volatility
input the LiveQuantEngine uses for the theoretical fair value (Theo Price) of Covered
Warrants.

Design contract
---------------
* ``get_estimate(symbol)`` / ``get_value(symbol)`` are PURE in-memory lookups. They never
  perform network, disk, or blocking I/O and are safe to call from the per-tick
  LiveQuantEngine calculation path.
* All upstream fetching happens in ``refresh()`` / ``warm()`` / ``run_periodic_refresh()``
  and in the fire-and-forget ``ensure()`` task, all of which run OUTSIDE the calculation
  path.
* Refreshes are single-flighted per underlying: concurrent callers for the same symbol
  share exactly one upstream request.
* The upstream source is abstracted behind ``HistoricalBarSource`` (one async method) so it
  can later be swapped from the FiinQuant provider to a PostgreSQL-backed source WITHOUT
  changing the LiveQuantEngine or this class' public surface.

Canonical window: HV_22 (22 trading sessions) - see ``app.core.config`` for the single
authoritative configuration value ``QUANT_HV_WINDOW_SESSIONS``.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional, Protocol, Sequence, Set

from app.core.config import settings
from app.market_data.market_schemas import (
    HistoricalRangeLimitError,
    HistoricalAuthError,
    HistoricalEntitlementError,
    HistoricalRateLimitError,
)
from app.quant.historical_volatility import calculate_historical_volatility

logger = logging.getLogger(__name__)

_VN_TZ = timezone(timedelta(hours=7))


def _vn_today() -> date:
    """Current Vietnam (UTC+7) calendar date."""
    return datetime.now(_VN_TZ).date()


@dataclass(frozen=True)
class VolEstimate:
    """Typed historical-volatility estimate with provenance metadata.

    Attributes
    ----------
    value : float
        Annualized volatility as a decimal (e.g. ``0.32`` == 32%).
    window : int
        Number of trading sessions of log-returns used.
    as_of : datetime.date
        Vietnam calendar date the estimate was computed.
    """

    value: float
    window: int
    as_of: date

    @property
    def source_label(self) -> str:
        """Provenance label, e.g. ``"HV_22"``. Derived from ``window`` - never hardcoded."""
        return f"HV_{self.window}"


class HistoricalBarSource(Protocol):
    """Minimal async interface required from an upstream historical-bar provider.

    ``FiinQuantProvider`` already satisfies this. A future PostgreSQL-backed source only
    needs to implement this one coroutine.
    """

    async def get_historical_bars(
        self,
        symbol: str,
        timeframe: str = "1D",
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        adjusted: bool = True,
    ) -> Sequence[object]:
        ...


class HistoricalVolatilityService:
    """In-memory HV cache keyed by underlying symbol with single-flighted async refresh."""

    def __init__(
        self,
        bar_source: Optional[HistoricalBarSource] = None,
        window_sessions: Optional[int] = None,
        min_sessions: Optional[int] = None,
        max_stale_days: Optional[int] = None,
        max_concurrent_refreshes: Optional[int] = None,
    ) -> None:
        self._source: Optional[HistoricalBarSource] = bar_source
        self._window: int = int(window_sessions or settings.QUANT_HV_WINDOW_SESSIONS)
        self._min_sessions: int = int(min_sessions or settings.QUANT_HV_MIN_SESSIONS)
        self._max_stale_days: int = int(
            max_stale_days if max_stale_days is not None else settings.QUANT_HV_MAX_STALE_DAYS
        )
        self._max_concurrent: int = int(
            max_concurrent_refreshes or settings.QUANT_HV_MAX_CONCURRENT_REFRESHES
        )

        self._cache: Dict[str, VolEstimate] = {}
        self._last_refresh_day: Dict[str, date] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
        self._sem = asyncio.Semaphore(self._max_concurrent)
        self._pending: Set[str] = set()          # underlyings with an in-flight ensure() task
        self._ensure_tasks: Set[asyncio.Task] = set()  # strong refs so tasks are not GC'd
        self._periodic_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------ #
    # Dependency injection (matches the LiveQuantEngine setter pattern)   #
    # ------------------------------------------------------------------ #
    def set_bar_source(self, source: HistoricalBarSource) -> None:
        """Injects the upstream historical-bar provider. Swap-point for PostgreSQL later."""
        self._source = source

    @property
    def window(self) -> int:
        return self._window

    # ------------------------------------------------------------------ #
    # PURE in-memory reads - safe to call from the per-tick quant path    #
    # (no network, no disk, no awaits, no locks)                          #
    # ------------------------------------------------------------------ #
    def get_estimate(self, symbol: str) -> Optional[VolEstimate]:
        """Return the cached HV estimate for an underlying, or ``None`` if absent/stale.

        Pure in-memory dict lookup. Never performs I/O. This is the callable wired into
        ``LiveQuantEngine.set_historical_vol_getter``.
        """
        if not symbol:
            return None
        est = self._cache.get(symbol.strip().upper())
        if est is None:
            return None
        if est.as_of > _vn_today() or (_vn_today() - est.as_of).days > self._max_stale_days:
            return None
        return est

    def get_value(self, symbol: str) -> Optional[float]:
        """Convenience: the decimal HV value only, or ``None``. Pure in-memory lookup."""
        est = self.get_estimate(symbol)
        return est.value if est is not None else None

    def has_fresh(self, symbol: str) -> bool:
        return self.get_estimate(symbol) is not None

    def cached_underlyings(self) -> List[str]:
        """Sorted list of underlyings that currently have any cached estimate."""
        return sorted(self._cache.keys())

    # ------------------------------------------------------------------ #
    # Async refresh - NEVER call from the per-tick calculation path       #
    # ------------------------------------------------------------------ #
    def _lock_for(self, symbol: str) -> asyncio.Lock:
        lock = self._locks.get(symbol)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[symbol] = lock
        return lock

    async def refresh(self, symbol: str, *, force: bool = False) -> Optional[VolEstimate]:
        """Fetch adjusted 1D closes for ``symbol`` and recompute its HV.

        Single-flighted per underlying via a per-symbol lock: concurrent callers for the
        same symbol collapse to one upstream request. Never raises - on any failure the
        previously cached estimate (if any) is preserved and returned.
        """
        sym = (symbol or "").strip().upper()
        if not sym:
            return None

        if self._source is None:
            logger.debug("HV refresh skipped for %s: no bar source wired yet.", sym)
            return self._cache.get(sym)

        async with self._lock_for(sym):
            # Another caller may have just refreshed it this VN day - reuse, no upstream call.
            existing = self._cache.get(sym)
            if not force and existing is not None and self._last_refresh_day.get(sym) == _vn_today():
                return existing

            try:
                async with self._sem:
                    bars = await self._source.get_historical_bars(
                        symbol=sym, timeframe="1D", adjusted=True
                    )
            except HistoricalRangeLimitError as exc:
                logger.warning(
                    "HV refresh for %s failed due to range limit: %s",
                    sym, exc,
                )
                return self._cache.get(sym)
            except (HistoricalAuthError, HistoricalEntitlementError) as exc:
                logger.warning(
                    "HV refresh for %s failed due to auth/entitlement error: %s: %s",
                    sym, exc.__class__.__name__, exc,
                )
                return self._cache.get(sym)
            except HistoricalRateLimitError as exc:
                logger.warning(
                    "HV refresh for %s rate-limited upstream: %s",
                    sym, exc,
                )
                return self._cache.get(sym)
            except Exception as exc:  # noqa: BLE001 - upstream failures must not propagate
                logger.warning(
                    "HV refresh for %s failed to fetch bars: %s: %s",
                    sym, exc.__class__.__name__, exc,
                )
                return self._cache.get(sym)

            observations: Dict[date, float] = {}
            for bar in bars or []:
                close = getattr(bar, "close", None)
                if close is None:
                    continue
                try:
                    c = float(close)
                except (TypeError, ValueError):
                    continue
                if c > 0:
                    raw_date = getattr(bar, "session_date", None) or getattr(bar, "date", None)
                    try:
                        bar_date = raw_date if isinstance(raw_date, date) else date.fromisoformat(str(raw_date)[:10])
                    except (TypeError, ValueError):
                        continue
                    if bar_date <= _vn_today():
                        observations[bar_date] = c

            ordered = sorted(observations.items())
            closes = [close for _, close in ordered]

            hv = calculate_historical_volatility(
                closes, window=self._window, min_periods=self._min_sessions
            )
            if hv is None or hv <= 0:
                logger.warning(
                    "HV refresh for %s: insufficient history "
                    "(%d valid closes; need >= %d returns); cached estimate unchanged.",
                    sym, len(closes), self._min_sessions,
                )
                return self._cache.get(sym)

            # Provenance is the final included bar, never the wall-clock refresh date.
            est = VolEstimate(value=hv, window=self._window, as_of=ordered[-1][0])
            self._cache[sym] = est
            self._last_refresh_day[sym] = _vn_today()
            logger.info("HV[%s] %s = %.4f (as_of %s)", est.source_label, sym, hv, est.as_of)
            return est

    async def warm(
        self, symbols: Sequence[str], timeout: Optional[float] = None
    ) -> Dict[str, Optional[VolEstimate]]:
        """Refresh many underlyings concurrently (bounded by the semaphore).

        Never raises. On timeout, returns whatever estimates are ready so far.
        """
        uniq = sorted({s.strip().upper() for s in symbols if s and s.strip()})
        if not uniq:
            return {}

        async def _one(s: str):
            try:
                return s, await self.refresh(s)
            except Exception as exc:  # noqa: BLE001 - defensive; refresh already guards
                logger.warning("HV warm-up for %s raised: %s: %s", s, exc.__class__.__name__, exc)
                return s, self._cache.get(s)

        gather = asyncio.gather(*[_one(s) for s in uniq], return_exceptions=True)
        try:
            results = await (asyncio.wait_for(gather, timeout) if timeout else gather)
        except asyncio.TimeoutError:
            gather.cancel()
            ready = sum(1 for s in uniq if s in self._cache)
            logger.warning(
                "HV warm-up timed out after %ss; %d/%d underlyings ready.",
                timeout, ready, len(uniq),
            )
            return {s: self._cache.get(s) for s in uniq}

        out: Dict[str, Optional[VolEstimate]] = {}
        for item in results:
            if isinstance(item, tuple):
                out[item[0]] = item[1]
        for s in uniq:
            out.setdefault(s, self._cache.get(s))
        return out

    def ensure(self, symbol: str) -> None:
        """Fire-and-forget async refresh for a newly-required underlying.

        Bounded: at most one in-flight ``ensure()`` task per symbol. No-op when the symbol
        already has a fresh estimate or when there is no running event loop. Safe to call
        from synchronous, non-async contexts (e.g. the WebSocket subscribe handler).
        """
        sym = (symbol or "").strip().upper()
        if not sym or sym in self._pending:
            return
        if self.has_fresh(sym):
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        self._pending.add(sym)

        async def _run() -> None:
            try:
                await self.refresh(sym)
            finally:
                self._pending.discard(sym)

        task = loop.create_task(_run())
        self._ensure_tasks.add(task)
        task.add_done_callback(self._ensure_tasks.discard)

    # ------------------------------------------------------------------ #
    # Optional background refresher (started from the app lifespan)       #
    # ------------------------------------------------------------------ #
    async def run_periodic_refresh(
        self,
        symbols_provider: Callable[[], Sequence[str]],
        interval_seconds: Optional[int] = None,
    ) -> None:
        """Loop forever, re-warming the current underlying set every ``interval_seconds``.

        Picks up newly-watched underlyings on each pass and keeps estimates from going
        stale. Cancellation-safe; each iteration is individually guarded.
        """
        interval = int(interval_seconds or settings.QUANT_HV_REFRESH_INTERVAL_SECONDS)
        while True:
            try:
                await asyncio.sleep(interval)
                symbols = list(symbols_provider() or [])
                if symbols:
                    await self.warm(symbols)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("HV periodic refresh iteration failed: %s: %s", exc.__class__.__name__, exc)

    def start_periodic_refresh(
        self,
        symbols_provider: Callable[[], Sequence[str]],
        interval_seconds: Optional[int] = None,
    ) -> None:
        if self._periodic_task is not None and not self._periodic_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._periodic_task = loop.create_task(
            self.run_periodic_refresh(symbols_provider, interval_seconds)
        )

    async def stop_periodic_refresh(self) -> None:
        task = self._periodic_task
        self._periodic_task = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

    # ------------------------------------------------------------------ #
    def stats(self) -> Dict[str, object]:
        """Sanitized observability snapshot."""
        return {
            "window_sessions": self._window,
            "min_sessions": self._min_sessions,
            "max_stale_days": self._max_stale_days,
            "cached_underlyings": sorted(self._cache.keys()),
            "cache_size": len(self._cache),
            "pending_ensures": sorted(self._pending),
            "source_wired": self._source is not None,
        }


# Global singleton (dependency-injected in app.main lifespan, mirrors live_quant_engine).
historical_volatility_service = HistoricalVolatilityService()
