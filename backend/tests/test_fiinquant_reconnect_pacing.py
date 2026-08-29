"""Deterministic tests for session-aware reconnect pacing.

In an active HOSE session a dropped stream is retried with the existing fast bounded
backoff. Outside the session FiinQuant closes the subscription streams within seconds, so
the provider must poll slowly instead of reconnecting every ~10s - while still waking at
the next session open. These tests pin the calendar via the injectable seams
(``_market_is_active`` / ``_seconds_to_next_session``); no wall-clock, no SDK, no network.
"""

import asyncio

import pytest

from app.market_data.providers.fiinquant_provider import FiinQuantProvider

pytestmark = pytest.mark.asyncio


def _provider(*, active: bool, secs_to_open: float = 9_999.0) -> FiinQuantProvider:
    p = FiinQuantProvider(username="u", password="p", max_symbols=33)
    p._market_is_active = lambda: active
    p._seconds_to_next_session = lambda: secs_to_open
    return p


async def test_in_session_uses_fast_bounded_backoff():
    p = _provider(active=True)
    assert p._compute_reconnect_delay() == 1.0  # index 0
    p._reconnect_backoff_index = 2
    assert p._compute_reconnect_delay() == 4.0
    p._reconnect_backoff_index = 99  # clamps to last entry
    assert p._compute_reconnect_delay() == 30.0


async def test_off_session_far_from_open_polls_at_slow_cadence():
    p = _provider(active=False, secs_to_open=9_999.0)
    assert p._compute_reconnect_delay() == p._off_session_reconnect_seconds == 300.0


async def test_off_session_near_open_wakes_at_open_not_later():
    p = _provider(active=False, secs_to_open=12.0)
    # Must not sleep past the open, and must not use the in-session 1s fast retry.
    assert p._compute_reconnect_delay() == 12.0


async def test_off_session_delay_never_below_current_backoff_floor():
    p = _provider(active=False, secs_to_open=0.5)
    p._reconnect_backoff_index = 3  # base = 8.0
    assert p._compute_reconnect_delay() == 8.0


async def test_calendar_error_falls_back_to_fast_backoff():
    p = _provider(active=False)

    def _boom():
        raise RuntimeError("calendar unavailable")

    p._market_is_active = _boom
    assert p._compute_reconnect_delay() == 1.0  # never wedges reconnect


async def test_worker_sleeps_for_the_computed_off_session_delay(monkeypatch):
    """The reconnect worker must honour the slow off-session delay (no ~1s tight loop)."""
    p = _provider(active=False, secs_to_open=9_999.0)
    p._active_symbols = ["HPG"]
    p._loop = asyncio.get_running_loop()

    slept: list[float] = []
    real_sleep = asyncio.sleep

    async def _capture(delay, *a, **kw):
        slept.append(delay)
        raise asyncio.CancelledError  # stop the worker right after the sleep call

    monkeypatch.setattr(asyncio, "sleep", _capture)
    try:
        await p._reconnect_worker()
    except asyncio.CancelledError:
        pass
    monkeypatch.setattr(asyncio, "sleep", real_sleep)

    assert slept == [300.0]


async def test_shutdown_cancels_a_slow_off_session_reconnect(monkeypatch):
    """A pending slow reconnect must not delay clean shutdown."""
    p = _provider(active=False, secs_to_open=9_999.0)
    p._active_symbols = ["HPG"]
    p._loop = asyncio.get_running_loop()
    p._schedule_reconnect()
    assert p._reconnect_task is not None

    await p.disconnect()
    assert p._reconnect_task is None
    assert p._shutting_down is True
