"""Sanitized, in-process counters for operator visibility via /health.

NEVER stores client IPs, user subjects, tokens, or abuse fingerprints - only aggregate
counts by policy/tier. Single-process (resets on restart); good enough to answer "are the
protections active and are they rejecting anything".
"""

from __future__ import annotations

import threading
from collections import defaultdict


class SecurityCounters:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._c: dict[str, int] = defaultdict(int)
        # gauges (current value, not cumulative)
        self._g: dict[str, int] = defaultdict(int)

    def incr(self, name: str, by: int = 1) -> None:
        with self._lock:
            self._c[name] += by

    def rate_limit_rejected(self, tier: str) -> None:
        self.incr("rate_limit.rejected_total")
        self.incr(f"rate_limit.rejected.{tier}")

    def set_gauge(self, name: str, value: int) -> None:
        with self._lock:
            self._g[name] = value

    def gauge_add(self, name: str, delta: int) -> None:
        with self._lock:
            self._g[name] = max(0, self._g[name] + delta)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "counters": dict(sorted(self._c.items())),
                "gauges": dict(sorted(self._g.items())),
            }

    def reset(self) -> None:
        """Test helper."""
        with self._lock:
            self._c.clear()
            self._g.clear()


security_counters = SecurityCounters()
