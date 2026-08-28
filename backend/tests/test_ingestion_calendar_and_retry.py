"""Pure-unit tests: Vietnam trading calendar + retry policy."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from app.market_data.market_schemas import (
    CIRCUIT_REASON_AUTH,
    CIRCUIT_REASON_RATE_LIMIT,
    HistoricalAuthError,
    HistoricalCircuitOpenError,
    HistoricalEntitlementError,
    HistoricalRangeLimitError,
    HistoricalRateLimitError,
    HistoricalTransportError,
    HistoricalUpstreamError,
)
from app.persistence.ingestion import trading_calendar as tc
from app.persistence.ingestion.retry import (
    RetryPolicy,
    call_with_retry,
    classify,
    is_retryable,
)
from app.persistence.market_time import VN_TZ
from datetime import date


# ---- calendar --------------------------------------------------------------
def test_weekend_and_fixed_holiday_are_not_expected_trading_days():
    assert tc.is_weekend(date(2026, 8, 29))          # Saturday
    assert not tc.is_expected_trading_day(date(2026, 8, 29))
    assert not tc.is_expected_trading_day(date(2026, 9, 2))   # National Day
    assert not tc.is_expected_trading_day(date(2026, 1, 1))   # New Year
    assert tc.is_expected_trading_day(date(2026, 8, 28))      # ordinary Friday


def test_tet_window_flagged_approximately():
    assert tc.in_tet_window(date(2026, 2, 17))
    assert not tc.in_tet_window(date(2026, 3, 17))


def test_last_completed_session_before_close_is_previous_day():
    # Friday 2026-08-28 10:00 VN -> not yet closed -> previous trading day (Thu 08-27)
    before_close = datetime(2026, 8, 28, 10, 0, tzinfo=VN_TZ)
    assert tc.last_completed_session_date(before_close) == date(2026, 8, 27)
    # Friday 16:00 VN -> today's session is final
    after_close = datetime(2026, 8, 28, 16, 0, tzinfo=VN_TZ)
    assert tc.last_completed_session_date(after_close) == date(2026, 8, 28)
    # Sunday -> last Friday
    sunday = datetime(2026, 8, 30, 12, 0, tzinfo=VN_TZ)
    assert tc.last_completed_session_date(sunday) == date(2026, 8, 28)


def test_intraday_bar_completeness():
    now = datetime(2026, 8, 28, 10, 7, tzinfo=VN_TZ)
    open_0930 = datetime(2026, 8, 28, 2, 30, tzinfo=timezone.utc)   # 09:30 VN
    assert tc.intraday_bar_is_complete(open_0930, 5, now)           # closes 09:35 < 10:07
    open_1005 = datetime(2026, 8, 28, 3, 5, tzinfo=timezone.utc)    # 10:05 VN
    assert not tc.intraday_bar_is_complete(open_1005, 5, now)       # closes 10:10 > 10:07


# ---- retry ---------------------------------------------------------------
def test_classification_and_retryability():
    assert is_retryable(HistoricalTransportError("x"))
    assert is_retryable(HistoricalUpstreamError("503"))
    assert is_retryable(HistoricalRateLimitError("429"))
    assert not is_retryable(HistoricalRangeLimitError("365"))
    assert not is_retryable(HistoricalAuthError("401"))
    assert not is_retryable(HistoricalEntitlementError("403"))
    assert classify(HistoricalRangeLimitError("x")) == "RANGE_LIMIT"
    assert classify(HistoricalRateLimitError("x")) == "RATE_LIMIT"


def test_circuit_open_retryability_is_driven_by_the_typed_reason():
    """No message-string sniffing: retry logic keys off HistoricalCircuitOpenError.reason."""
    auth_open = HistoricalCircuitOpenError(
        "circuit breaker is OPEN (AUTH_FAILURE)", reason=CIRCUIT_REASON_AUTH, retry_after_seconds=55.0
    )
    rate_open = HistoricalCircuitOpenError(
        "circuit breaker is OPEN (RATE_LIMIT)", reason=CIRCUIT_REASON_RATE_LIMIT, retry_after_seconds=8.0
    )
    assert is_retryable(auth_open) is False        # auth circuit never self-heals
    assert is_retryable(rate_open) is True         # rate-limit circuit clears on its own
    assert auth_open.is_retryable is False and rate_open.is_retryable is True
    assert classify(auth_open) == "CIRCUIT_OPEN[AUTH_FAILURE]"
    assert classify(rate_open) == "CIRCUIT_OPEN[RATE_LIMIT]"


def test_backoff_is_bounded_and_jittered():
    pol = RetryPolicy(max_retries=5, base_seconds=2.0, max_seconds=30.0)
    for attempt in range(1, 8):
        for _ in range(50):
            d = pol.backoff_seconds(attempt)
            assert 0.0 <= d <= 30.0
    # rate-limited doubles the (pre-cap) base
    assert pol.backoff_seconds(1, rate_limited=True) <= 30.0


@pytest.mark.asyncio
async def test_call_with_retry_succeeds_after_transient_failures():
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise HistoricalTransportError("boom")
        return "ok"

    result, attempts = await call_with_retry(
        flaky, policy=RetryPolicy(max_retries=5, base_seconds=0.0, max_seconds=0.0),
        sleep=lambda _s: asyncio.sleep(0),
    )
    assert result == "ok" and attempts == 2 and calls["n"] == 3


@pytest.mark.asyncio
async def test_call_with_retry_recovers_from_rate_limit_circuit():
    slept: list[float] = []

    async def _sleep(s):
        slept.append(s)

    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise HistoricalCircuitOpenError(
                "circuit breaker is OPEN (RATE_LIMIT)", reason=CIRCUIT_REASON_RATE_LIMIT,
                retry_after_seconds=9.0,
            )
        return "ok"

    result, attempts = await call_with_retry(
        flaky, policy=RetryPolicy(max_retries=5, base_seconds=1.0, max_seconds=60.0), sleep=_sleep
    )
    assert result == "ok" and attempts == 2
    assert all(s >= 10.0 for s in slept)   # never retries before the circuit's own cooldown


@pytest.mark.asyncio
async def test_call_with_retry_does_not_retry_auth_circuit_open():
    calls = {"n": 0}

    async def blocked():
        calls["n"] += 1
        raise HistoricalCircuitOpenError(
            "circuit breaker is OPEN (AUTH_FAILURE)", reason=CIRCUIT_REASON_AUTH, retry_after_seconds=55.0
        )

    with pytest.raises(HistoricalCircuitOpenError):
        await call_with_retry(blocked, policy=RetryPolicy(4, 0.0, 0.0), sleep=lambda _s: asyncio.sleep(0))
    assert calls["n"] == 1   # halted on the first attempt, no retry storm


@pytest.mark.asyncio
async def test_call_with_retry_does_not_retry_non_retryable():
    calls = {"n": 0}

    async def bad():
        calls["n"] += 1
        raise HistoricalRangeLimitError("too far")

    with pytest.raises(HistoricalRangeLimitError):
        await call_with_retry(bad, policy=RetryPolicy(3, 0.0, 0.0), sleep=lambda _s: asyncio.sleep(0))
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_call_with_retry_exhausts_and_raises_last():
    async def always():
        raise HistoricalUpstreamError("502")

    with pytest.raises(HistoricalUpstreamError):
        await call_with_retry(always, policy=RetryPolicy(2, 0.0, 0.0), sleep=lambda _s: asyncio.sleep(0))
