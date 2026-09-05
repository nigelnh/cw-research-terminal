"""Centralized rate limiter.

Thin wrapper over the well-tested ``limits`` library (moving-window strategy) - no
home-grown distributed algorithm. Backends:

  * ``memory``  - in-process ``MemoryStorage`` (local dev, CI, single-worker demos)
  * ``redis``   - shared ``RedisStorage`` keyed under ``cw_research:ratelimit:v1`` -
                  a namespace fully separate from the market-state warm cache

Selection (``RATE_LIMIT_BACKEND``): ``auto`` picks redis when ``REDIS_ENABLED`` and a URL
resolves and it answers, else memory.

Degradation when a configured redis backend errors mid-request:
  * AI (``fail_closed``)                -> deny (it costs real money)
  * ``RATE_LIMIT_FAIL_OPEN`` true       -> allow
  * otherwise                           -> a conservative in-process fallback limiter
                                           (never "unlimited")
Every degradation is counted and surfaced in ``health()``.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass

from limits import (
    RateLimitItemPerDay,
    RateLimitItemPerHour,
    RateLimitItemPerMinute,
    RateLimitItemPerSecond,
)
from limits.aio.storage import MemoryStorage
from limits.aio.strategies import MovingWindowRateLimiter

from app.core.config import settings
from app.security.observability import security_counters

logger = logging.getLogger("cw-research-backend.security")

_KEY_PREFIX = "cw_research:ratelimit:v1"

RateLimitItem = RateLimitItemPerMinute | RateLimitItemPerHour | RateLimitItemPerDay | RateLimitItemPerSecond


def per_minute(n: int) -> RateLimitItemPerMinute:
    return RateLimitItemPerMinute(max(1, int(n)))


def per_hour(n: int) -> RateLimitItemPerHour:
    return RateLimitItemPerHour(max(1, int(n)))


def per_day(n: int) -> RateLimitItemPerDay:
    """Calendar-window daily cap (the ``limits`` moving-window strategy still applies -
    this is a rolling 24h window, not a UTC-midnight reset). Used by tiers with a stateful
    daily allowance (e.g. the AI tier's guest/signed-in quotas) alongside a per-minute
    burst item from the same tier - both must pass."""
    return RateLimitItemPerDay(max(1, int(n)))


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    retry_after: int
    tier: str
    degraded: bool = False


class RateLimiterStartupError(RuntimeError):
    """The rate limiter cannot start in a configuration that is safe for production."""


class RateLimiter:
    def __init__(self) -> None:
        self._primary: MovingWindowRateLimiter | None = None
        self._fallback: MovingWindowRateLimiter | None = None
        self._mode: str = "uninitialized"
        self._degraded_seen = False
        self._configured = False

    @property
    def mode(self) -> str:
        return self._mode

    async def configure(self) -> None:
        """Build the storage backend.

        Fail-safe policy (only ``ENVIRONMENT=production`` with rate limiting enabled is
        strict; dev/CI keep the convenient auto/memory fallback):

          * ``RATE_LIMIT_BACKEND=redis``  + redis unreachable  -> raise (fail startup)
          * ``RATE_LIMIT_BACKEND=memory`` + not ALLOW_SINGLE_PROCESS_RATE_LIMIT -> raise
          * ``RATE_LIMIT_BACKEND=auto``   -> must resolve to redis; if it would fall back
                                             to memory -> raise (unless the override is set)

        Safe to call again (tests do).
        """
        self._fallback = MovingWindowRateLimiter(MemoryStorage())

        requested = (settings.RATE_LIMIT_BACKEND or "auto").strip().lower()
        url = settings.rate_limit_redis_url()
        strict = (
            settings.is_production()
            and settings.PUBLIC_RATE_LIMIT_ENABLED
            and not settings.ALLOW_SINGLE_PROCESS_RATE_LIMIT
        )
        want_redis = requested in ("redis", "auto") and (
            requested == "redis" or (settings.REDIS_ENABLED and bool(url))
        )

        if strict and requested == "memory":
            raise RateLimiterStartupError(
                "RATE_LIMIT_BACKEND=memory with ENVIRONMENT=production: a per-process limiter "
                "is not shared across workers. Use Redis, or set "
                "ALLOW_SINGLE_PROCESS_RATE_LIMIT=true for a documented single-worker demo."
            )

        if want_redis and url:
            try:
                from limits.aio.storage import RedisStorage

                scheme_url = url if url.startswith("async+") else f"async+{url}"
                storage = RedisStorage(scheme_url, implementation="redispy", key_prefix=_KEY_PREFIX)
                ok = await storage.check()
                if not ok:
                    raise RuntimeError("redis limiter storage check() returned False")
                self._primary = MovingWindowRateLimiter(storage)
                self._mode = "redis"
                self._configured = True
                logger.info("Rate limiter backend: redis (%s)", _KEY_PREFIX)
                return
            except Exception as exc:  # noqa: BLE001
                if strict:
                    raise RateLimiterStartupError(
                        f"RATE_LIMIT_BACKEND={requested} but the Redis limiter is unavailable "
                        f"({exc.__class__.__name__}). Production requires a working shared limiter. "
                        "Fix Redis or set ALLOW_SINGLE_PROCESS_RATE_LIMIT=true for a single-worker demo."
                    ) from exc
                logger.warning(
                    "Rate limiter: redis backend unavailable (%s); using in-process memory. "
                    "In a multi-worker deployment this makes limits per-worker.",
                    exc.__class__.__name__,
                )

        if requested == "redis" and not url:
            msg = "RATE_LIMIT_BACKEND=redis but no Redis URL is configured (RATE_LIMIT_REDIS_URL / REDIS_URL)."
            if strict:
                raise RateLimiterStartupError(msg)
            logger.error("%s Falling back to per-process memory.", msg)
        elif strict and requested == "auto":
            raise RateLimiterStartupError(
                "RATE_LIMIT_BACKEND=auto with ENVIRONMENT=production resolved to an in-process "
                "memory limiter (REDIS_ENABLED false or no URL). Configure Redis, or set "
                "ALLOW_SINGLE_PROCESS_RATE_LIMIT=true for a documented single-worker demo."
            )

        self._primary = MovingWindowRateLimiter(MemoryStorage())
        self._mode = "memory"
        self._configured = True
        if requested == "redis":
            logger.error(
                "RATE_LIMIT_BACKEND=redis but redis is unreachable - running with a per-process "
                "memory limiter. Fix redis before relying on distributed limits."
            )

    async def check(
        self,
        *,
        tier: str,
        key: str,
        items: tuple[RateLimitItem, ...],
        fail_closed: bool = False,
    ) -> RateLimitDecision:
        """Consume one hit against every ``item`` (all must pass). ``key`` already carries
        the client identity (ip:/sub:); we namespace by tier so tiers don't share budgets."""
        if not self._configured or self._primary is None:
            await self.configure()
        assert self._primary is not None

        namespaced = f"{tier}:{key}"
        try:
            for item in items:
                if not await self._primary.hit(item, namespaced):
                    stats = await self._primary.get_window_stats(item, namespaced)
                    retry = max(1, math.ceil(stats.reset_time - time.time()))
                    security_counters.rate_limit_rejected(tier)
                    return RateLimitDecision(False, retry, tier)
            return RateLimitDecision(True, 0, tier)
        except Exception as exc:  # noqa: BLE001 - redis mid-request failure
            self._degraded_seen = True
            security_counters.incr("rate_limit.backend_errors_total")
            logger.warning("Rate limiter backend error (%s); degrading", exc.__class__.__name__)

            if fail_closed:
                security_counters.rate_limit_rejected(f"{tier}:fail_closed")
                return RateLimitDecision(False, 5, tier, degraded=True)
            if settings.RATE_LIMIT_FAIL_OPEN:
                return RateLimitDecision(True, 0, tier, degraded=True)

            # conservative in-process fallback - bounded, never unlimited
            assert self._fallback is not None
            try:
                for item in items:
                    if not await self._fallback.hit(item, namespaced):
                        stats = await self._fallback.get_window_stats(item, namespaced)
                        retry = max(1, math.ceil(stats.reset_time - time.time()))
                        security_counters.rate_limit_rejected(f"{tier}:degraded")
                        return RateLimitDecision(False, retry, tier, degraded=True)
                return RateLimitDecision(True, 0, tier, degraded=True)
            except Exception:  # noqa: BLE001
                return RateLimitDecision(False, 5, tier, degraded=True)

    async def reset(self) -> None:
        """Test helper - wipe all counters."""
        for lim in (self._primary, self._fallback):
            if lim is not None:
                try:
                    await lim.storage.reset()
                except Exception:  # noqa: BLE001, S110 - best-effort test cleanup
                    pass

    def health(self) -> dict:
        return {
            "enabled": bool(settings.PUBLIC_RATE_LIMIT_ENABLED),
            "backend": self._mode,
            "degraded_since_start": self._degraded_seen,
            "fail_open": bool(settings.RATE_LIMIT_FAIL_OPEN),
            "trust_proxy": bool(settings.RATE_LIMIT_TRUST_PROXY),
        }


rate_limiter = RateLimiter()
