"""Root test configuration.

Step 10 adds HTTP rate limiting / body caps / security headers as always-on middleware.
For the existing suite (which fires many requests per test and asserts business behavior)
we keep the *rate limiter* disabled by default and force the in-process memory backend, so
no test depends on a running Redis for limiter behavior and no test trips a 429 it did not
ask for. The dedicated Step-10 tests re-enable it explicitly via ``rate_limit_enabled``.

Body-size and security-header middleware stay active everywhere (cheap, deterministic).

It also provides ``display_session_ms``: the suite has to be runnable at any hour, and
several tests need a timestamp that lands inside the session the app is currently
DISPLAYING - which is not the same as "now".
"""

from __future__ import annotations

import asyncio
from datetime import datetime, time as dt_time

import pytest

from app.core.config import settings
from app.market_data.session_reference import reference_session_date
from app.market_data.trading_calendar import VN_TZ
from app.security.observability import security_counters
from app.security.policies import policy_table
from app.security.rate_limiter import rate_limiter


def _reset_limiter_singleton() -> None:
    policy_table.cache_clear()
    rate_limiter._configured = False
    rate_limiter._primary = None
    rate_limiter._fallback = None
    rate_limiter._degraded_seen = False
    security_counters.reset()


@pytest.fixture(autouse=True)
def _limiter_defaults(monkeypatch):
    monkeypatch.setattr(settings, "PUBLIC_RATE_LIMIT_ENABLED", False)
    monkeypatch.setattr(settings, "RATE_LIMIT_BACKEND", "memory")
    yield


@pytest.fixture
def rate_limit_enabled(monkeypatch):
    """Enable a deterministic in-process rate limiter for one test. The limiter configures
    itself lazily on first use (inside the ASGI portal loop); we just flip the flags and
    wipe state before and after."""
    monkeypatch.setattr(settings, "PUBLIC_RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_BACKEND", "memory")
    _reset_limiter_singleton()
    yield rate_limiter
    try:
        asyncio.run(rate_limiter.reset())
    except RuntimeError:
        pass
    _reset_limiter_singleton()


def display_session_ms(offset_ms: int = 0, now: datetime | None = None) -> int:
    """An epoch-ms timestamp inside the session the app is currently displaying.

    ``get_vn_now()`` is NOT interchangeable with this. Before the open, after midnight, at
    a weekend or on a holiday, the displayed session is an earlier calendar day - and
    hydration compares a cached quote's date against THAT day, so a quote stamped "now" is
    a different session and gets its intraday fields correctly sanitized.

    Tests that mean "this cache entry is from the current session" must therefore anchor to
    the display day rather than the wall clock. Anchoring to "now" is why several of them
    passed during trading hours and failed at 00:46 ICT. 10:00 ICT is used as the in-session
    instant: comfortably inside the morning continuous session on any trading day.

    `now` exists so the invariant can be asserted at arbitrary instants without freezing the
    process clock; production callers pass nothing.
    """
    day = reference_session_date(now)
    anchor = datetime.combine(day, dt_time(10, 0), tzinfo=VN_TZ)
    return int(anchor.timestamp() * 1000) + offset_ms
