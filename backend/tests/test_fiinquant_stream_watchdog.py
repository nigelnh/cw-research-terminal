"""Deterministic tests for the stream-liveness watchdog.

FiinQuant can stop pushing frames without ever firing ``on_close``: the SDK still reports
the stream connected, no reconnect is scheduled, and the feed is dead for the rest of the
session. Observed in production 2026-09-07 - last trade tick 09:41 ICT, still "connected"
at 10:51 with ``reconnect_count: 0``, so ``MatchVolume`` (TRD_AMT) never advanced.

``get_health()`` already computed ``STALE`` for exactly this state, but it is pull-based
and nothing acted on it. These tests pin ``_silent_stream_age_seconds`` - the judgement the
watchdog loop acts on - through the injectable calendar seams. No wall-clock, no SDK, no
network.
"""

import time

import pytest

from app.market_data.providers.fiinquant_provider import FiinQuantProvider

pytestmark = pytest.mark.asyncio


def _provider(*, active: bool = True, silence: float = 90.0) -> FiinQuantProvider:
    p = FiinQuantProvider(username="u", password="p", max_symbols=33)
    p._market_is_active = lambda: active
    p._seconds_to_next_session = lambda: 9_999.0
    p._stream_silence_reconnect_seconds = silence
    # A live, connected stream carrying symbols.
    p._is_connected = True
    p._active_symbols = ["HPG", "CHPG2627"]
    p._upstream_status = "CONNECTED"
    return p


def _stream_up_for(p: FiinQuantProvider, seconds: float) -> None:
    p._current_stream_started_at_monotonic = time.monotonic() - seconds


def _last_tick_seconds_ago(p: FiinQuantProvider, seconds: float) -> None:
    p._current_stream_last_tick_at_ms = int((time.time() - seconds) * 1000)


async def test_silent_stream_past_the_budget_is_reported():
    """The production failure: connected, in-session, no frame for 70 minutes."""
    p = _provider(silence=90.0)
    _stream_up_for(p, 4200)
    _last_tick_seconds_ago(p, 4200)
    age = p._silent_stream_age_seconds()
    assert age is not None and age >= 4000
    assert age >= p._stream_silence_reconnect_seconds


async def test_a_recently_ticking_stream_is_not_silent():
    p = _provider(silence=90.0)
    _stream_up_for(p, 600)
    _last_tick_seconds_ago(p, 5)
    age = p._silent_stream_age_seconds()
    assert age is not None and age < p._stream_silence_reconnect_seconds


async def test_a_stream_that_never_ticked_counts_its_whole_uptime():
    """No frame at all since start - silence is measured from the stream's own start."""
    p = _provider(silence=90.0)
    _stream_up_for(p, 300)
    p._current_stream_last_tick_at_ms = None
    age = p._silent_stream_age_seconds()
    assert age is not None and age >= 300


async def test_a_warming_up_stream_is_given_the_full_budget():
    """A slow first frame must never be mistaken for a dead feed."""
    p = _provider(silence=90.0)
    _stream_up_for(p, 20)  # younger than the budget
    p._current_stream_last_tick_at_ms = None
    assert p._silent_stream_age_seconds() is None


async def test_off_session_silence_is_never_judged():
    """FiinQuant legitimately stops pushing at lunch / pre-open / post-close."""
    p = _provider(active=False, silence=90.0)
    _stream_up_for(p, 4200)
    _last_tick_seconds_ago(p, 4200)
    assert p._silent_stream_age_seconds() is None


async def test_an_in_flight_reconnect_is_not_stacked_on():
    p = _provider(silence=90.0)
    _stream_up_for(p, 4200)
    _last_tick_seconds_ago(p, 4200)
    p._upstream_status = "RESTARTING"
    assert p._silent_stream_age_seconds() is None


async def test_no_judgement_without_a_stream_or_symbols():
    p = _provider(silence=90.0)
    _stream_up_for(p, 4200)
    _last_tick_seconds_ago(p, 4200)

    p._active_symbols = []
    assert p._silent_stream_age_seconds() is None

    p._active_symbols = ["HPG"]
    p._is_connected = False
    assert p._silent_stream_age_seconds() is None

    p._is_connected = True
    p._current_stream_started_at_monotonic = None
    assert p._silent_stream_age_seconds() is None


async def test_a_calendar_fault_never_triggers_a_reconnect():
    """A broken trading calendar must fail closed, not start a reconnect storm."""
    def _boom() -> bool:
        raise RuntimeError("calendar down")

    p = _provider(silence=90.0)
    p._market_is_active = _boom
    _stream_up_for(p, 4200)
    _last_tick_seconds_ago(p, 4200)
    assert p._silent_stream_age_seconds() is None


async def test_watchdog_is_disabled_when_the_budget_is_zero():
    p = _provider(silence=0.0)
    p._ensure_stream_watchdog()
    assert p._stream_watchdog_task is None


async def test_watchdog_start_is_idempotent():
    p = _provider(silence=90.0)
    p._stream_watchdog_interval_seconds = 3600.0  # never fires during the test
    try:
        p._ensure_stream_watchdog()
        first = p._stream_watchdog_task
        assert first is not None
        p._ensure_stream_watchdog()
        assert p._stream_watchdog_task is first  # not replaced
    finally:
        if p._stream_watchdog_task is not None:
            p._stream_watchdog_task.cancel()


async def test_health_exposes_the_watchdog_counters():
    p = _provider(silence=90.0)
    health = p.get_health()
    assert health["silent_stream_reconnect_count"] == 0
    assert health["stream_silence_reconnect_seconds"] == 90.0
    assert "stream_watchdog_active" in health


async def test_market_health_endpoint_surfaces_the_watchdog():
    """The counters are useless if the sanitized endpoint drops them - that is how the
    original silent-stream failure stayed invisible for 70 minutes."""
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        body = client.get("/api/market/health").json()

    for key in (
        "silent_stream_reconnect_count",
        "stream_watchdog_active",
        "stream_silence_reconnect_seconds",
        "trade_tick_age_seconds",
    ):
        assert key in body, f"{key} missing from /api/market/health"
