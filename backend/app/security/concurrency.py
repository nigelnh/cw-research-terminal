"""Small, targeted global concurrency guards.

A rate limit bounds *how often* a client starts work; it does not bound how many clients
start expensive work at the same instant. These bounded gates do - only around the two
places that matter:

  * ``ai_call_gate``          - upstream AI calls (real monetary cost)
  * ``history_gapfill_gate``  - distinct history streams triggering a provider gap-fill

There is deliberately NO gate around plain API handlers or DB-only history hits: those
must stay cheap and fully concurrent.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator

from app.security.observability import security_counters


class BoundedGate:
    """A lazily-created asyncio.Semaphore with an acquire timeout and live counters."""

    def __init__(self, name: str, limit: int) -> None:
        self._name = name
        self._limit = max(1, int(limit))
        self._sem: asyncio.Semaphore | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def _semaphore(self) -> asyncio.Semaphore:
        # Rebind if the running loop changed (production has one loop for life; the test
        # suite creates a fresh loop per test - a stale Semaphore would raise cross-loop).
        loop = asyncio.get_running_loop()
        if self._sem is None or self._loop is not loop:
            self._sem = asyncio.Semaphore(self._limit)
            self._loop = loop
        return self._sem

    def set_limit(self, limit: int) -> None:
        """Rebuild the gate with a new limit. For startup wiring / tests only - callers
        must ensure nothing currently holds the gate."""
        self._limit = max(1, int(limit))
        self._sem = None
        self._loop = None

    @property
    def limit(self) -> int:
        return self._limit

    @property
    def in_flight(self) -> int:
        sem = self._sem
        if sem is None:
            return 0
        return self._limit - sem._value  # best-effort gauge

    @contextlib.asynccontextmanager
    async def acquire(self, timeout: float) -> AsyncIterator[None]:
        sem = self._semaphore()
        try:
            await asyncio.wait_for(sem.acquire(), timeout=timeout)
        except (TimeoutError, asyncio.TimeoutError) as exc:  # noqa: UP041 - be explicit
            security_counters.incr(f"{self._name}.rejected_saturated_total")
            raise GateTimeout(self._name) from exc
        security_counters.set_gauge(f"{self._name}.in_flight", self.in_flight)
        try:
            yield
        finally:
            sem.release()
            security_counters.set_gauge(f"{self._name}.in_flight", self.in_flight)

    def try_acquire_nowait(self) -> bool:
        sem = self._semaphore()
        if sem.locked() or sem._value <= 0:
            security_counters.incr(f"{self._name}.rejected_saturated_total")
            return False
        # not truly atomic with the release path, but adequate for a soft global cap
        return True


class GateTimeout(RuntimeError):
    def __init__(self, name: str) -> None:
        super().__init__(f"{name}: no capacity within timeout")
        self.gate = name


def _ai_limit() -> int:
    from app.core.config import settings

    return settings.AI_MAX_CONCURRENT


def _gapfill_limit() -> int:
    from app.core.config import settings

    return settings.HISTORY_MAX_CONCURRENT_GAPFILLS


ai_call_gate = BoundedGate("ai_calls", _ai_limit())
history_gapfill_gate = BoundedGate("history_gapfill", _gapfill_limit())
