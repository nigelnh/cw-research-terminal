"""Root test configuration.

Step 10 adds HTTP rate limiting / body caps / security headers as always-on middleware.
For the existing suite (which fires many requests per test and asserts business behavior)
we keep the *rate limiter* disabled by default and force the in-process memory backend, so
no test depends on a running Redis for limiter behavior and no test trips a 429 it did not
ask for. The dedicated Step-10 tests re-enable it explicitly via ``rate_limit_enabled``.

Body-size and security-header middleware stay active everywhere (cheap, deterministic).
"""

from __future__ import annotations

import asyncio

import pytest

from app.core.config import settings
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
