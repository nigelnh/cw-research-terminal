"""Tests for FiinQuant historical data fetch error classification, range limit, and circuit breaker.

Invariant:
* An explicit > 365 days range is never silently truncated (raises HistoricalRangeLimitError).
* TimeFrameLimitFailed is classified as RANGE_LIMIT.
* RANGE_LIMIT does NOT open the provider-wide auth/entitlement circuit breaker.
* A valid short request succeeds immediately after a range-limit failure.
* Auth failure (401) opens the circuit breaker for a cooldown period.
* Rate limit (429), entitlement (403), transport, and upstream (5xx) are accurately classified.

No real FiinQuant network calls are made: exercised via mock session seam.
"""

from datetime import datetime
import pandas as pd
import pytest

from app.market_data.market_schemas import (
    CIRCUIT_REASON_AUTH,
    CIRCUIT_REASON_RATE_LIMIT,
    HistoricalAuthError,
    HistoricalBar,
    HistoricalCircuitOpenError,
    HistoricalEntitlementError,
    HistoricalRangeLimitError,
    HistoricalRateLimitError,
    HistoricalTransportError,
    HistoricalUpstreamError,
)
from app.market_data.providers.fiinquant_provider import FiinQuantProvider

pytestmark = pytest.mark.asyncio


class _FakeHistorySession:
    def __init__(self, fail_mode: str = "ok"):
        self.is_login = True
        self.access_token = "fake-jwt-token"
        self.fail_mode = fail_mode
        self.call_log = []

    def Fetch_Trading_Data(self, realtime, tickers, fields, by, from_date, to_date, adjusted):
        self.call_log.append({
            "tickers": tickers,
            "by": by,
            "from_date": from_date,
            "to_date": to_date,
            "adjusted": adjusted,
        })
        if self.fail_mode == "ok":
            df = pd.DataFrame([
                {"TradingDate": "2026-08-26", "open": 22000.0, "high": 22500.0, "low": 21900.0, "close": 22200.0, "volume": 15000000.0},
                {"TradingDate": "2026-08-27", "open": 22200.0, "high": 22400.0, "low": 22050.0, "close": 22200.0, "volume": 12000000.0},
            ])
            return df
        elif self.fail_mode == "timeframe_limit":
            raise RuntimeError("TimeFrameLimitFailed: You can only access data up to 365 days from the present time.")
        elif self.fail_mode == "auth_401":
            raise RuntimeError("401 Client Error: Unauthorized (invalid_token)")
        elif self.fail_mode == "entitlement_403":
            raise RuntimeError("403 Client Error: Forbidden (EntitlementRequired for tier Pro)")
        elif self.fail_mode == "rate_limit_429":
            raise RuntimeError("429 Client Error: RateLimitExceeded")
        elif self.fail_mode == "server_error_503":
            raise RuntimeError("503 Server Error: Service Unavailable")
        elif self.fail_mode == "transport_drop":
            raise ConnectionResetError("Connection dropped by remote peer")
        elif self.fail_mode == "empty":
            return pd.DataFrame()
        else:
            raise ValueError(f"Unknown fail_mode {self.fail_mode}")


def _make_history_provider(fail_mode: str = "ok") -> tuple[FiinQuantProvider, _FakeHistorySession]:
    p = FiinQuantProvider(username="test_user", password="test_password")
    session = _FakeHistorySession(fail_mode=fail_mode)
    p._create_session = lambda: session
    return p, session


async def test_default_lookback_uses_safe_360_days():
    p, sess = _make_history_provider("ok")
    bars = await p.get_historical_bars("HPG", timeframe="1D")

    assert len(bars) == 2
    assert isinstance(bars[0], HistoricalBar)
    assert bars[0].close == 22200.0
    assert len(sess.call_log) == 1
    call = sess.call_log[0]
    dt_from = datetime.strptime(call["from_date"], "%Y-%m-%d").date()
    dt_to = datetime.strptime(call["to_date"], "%Y-%m-%d").date()
    # Default lookback must be <= 360 days
    assert (dt_to - dt_from).days <= 361
    assert p.get_health()["historical_status"] == "HEALTHY"


async def test_explicit_over_limit_range_raises_range_limit_error_without_silent_truncation():
    p, sess = _make_history_provider("ok")

    # Requesting 2 years explicitly
    with pytest.raises(HistoricalRangeLimitError) as exc_info:
        await p.get_historical_bars("HPG", timeframe="1D", from_date="2024-01-01", to_date="2026-08-27")

    assert "exceeds upstream timeframe limit" in str(exc_info.value)
    # Upstream must NOT have been called with silently truncated dates
    assert len(sess.call_log) == 0


async def test_upstream_timeframe_limit_failure_classified_as_range_limit():
    p, sess = _make_history_provider("timeframe_limit")

    # Request within nominal 365 days that upstream rejects with TimeFrameLimitFailed
    with pytest.raises(HistoricalRangeLimitError) as exc_info:
        await p.get_historical_bars("HPG", timeframe="1D", from_date="2025-08-28", to_date="2026-08-27")

    assert "TimeFrameLimitFailed" in str(exc_info.value)


async def test_range_limit_does_not_open_circuit_breaker_and_subsequent_short_request_succeeds():
    p, sess = _make_history_provider("ok")

    # 1. First request fails with range limit
    with pytest.raises(HistoricalRangeLimitError):
        await p.get_historical_bars("HPG", timeframe="1D", from_date="2024-01-01", to_date="2026-08-27")

    # Invariant: Circuit breaker is NOT open
    health = p.get_health()
    assert health["historical_circuit_open"] is False
    assert health["historical_status"] == "HEALTHY"

    # 2. Subsequent valid short request succeeds immediately
    bars = await p.get_historical_bars("HPG", timeframe="1D", from_date="2026-08-01", to_date="2026-08-27")
    assert len(bars) == 2
    assert bars[0].close == 22200.0
    assert len(sess.call_log) == 1  # only the valid request reached upstream


async def test_auth_failure_opens_circuit_breaker_and_cooldown_blocks_subsequent_calls():
    p, sess = _make_history_provider("auth_401")

    # 1. A genuine auth failure raises HistoricalAuthError (NOT the circuit-open type)
    with pytest.raises(HistoricalAuthError) as exc_info:
        await p.get_historical_bars("HPG", timeframe="1D")
    assert not isinstance(exc_info.value, HistoricalCircuitOpenError)
    assert "auth failure" in str(exc_info.value).lower()
    health = p.get_health()
    assert health["historical_circuit_open"] is True
    assert health["historical_status"] == "DEGRADED"

    # 2. A subsequent call is blocked by the OPEN circuit without hitting upstream. It
    #    raises the typed HistoricalCircuitOpenError carrying the canonical reason.
    calls_before = len(sess.call_log)
    with pytest.raises(HistoricalCircuitOpenError) as exc_info2:
        await p.get_historical_bars("SSI", timeframe="1D")
    err = exc_info2.value
    assert err.reason == CIRCUIT_REASON_AUTH
    assert err.is_retryable is False                       # an auth circuit does not self-heal
    assert err.retry_after_seconds > 0
    assert "circuit breaker is OPEN" in str(err)
    assert len(sess.call_log) == calls_before              # no new upstream hit while circuit is open


async def test_rate_limit_opens_circuit_and_subsequent_call_is_retryable_circuit_open():
    p, sess = _make_history_provider("rate_limit_429")

    # 1. A 429 raises HistoricalRateLimitError and opens the circuit with a short cooldown
    with pytest.raises(HistoricalRateLimitError) as exc_info:
        await p.get_historical_bars("HPG", timeframe="1D")
    assert not isinstance(exc_info.value, HistoricalCircuitOpenError)
    assert p.get_health()["historical_circuit_open"] is True

    # 2. A subsequent call is blocked by the OPEN circuit -> HistoricalCircuitOpenError,
    #    reason RATE_LIMIT, and it IS retryable (the circuit clears on its own).
    calls_before = len(sess.call_log)
    with pytest.raises(HistoricalCircuitOpenError) as exc_info2:
        await p.get_historical_bars("SSI", timeframe="1D")
    err = exc_info2.value
    assert err.reason == CIRCUIT_REASON_RATE_LIMIT
    assert err.is_retryable is True
    assert 0 < err.retry_after_seconds <= 10.0
    assert len(sess.call_log) == calls_before


async def test_entitlement_failure_classification():
    p, sess = _make_history_provider("entitlement_403")

    with pytest.raises(HistoricalEntitlementError) as exc_info:
        await p.get_historical_bars("SPECIAL_TICKER", timeframe="1D")

    assert "entitlement failure" in str(exc_info.value).lower()
    assert p.get_health()["historical_status"] == "DEGRADED"


async def test_rate_limit_classification():
    p, sess = _make_history_provider("rate_limit_429")

    with pytest.raises(HistoricalRateLimitError) as exc_info:
        await p.get_historical_bars("HPG", timeframe="1D")

    assert "rate limit" in str(exc_info.value).lower()


async def test_upstream_server_error_classification():
    p, sess = _make_history_provider("server_error_503")

    with pytest.raises(HistoricalUpstreamError) as exc_info:
        await p.get_historical_bars("HPG", timeframe="1D")

    assert "upstream server error" in str(exc_info.value).lower()


async def test_transport_error_classification():
    p, sess = _make_history_provider("transport_drop")

    with pytest.raises(HistoricalTransportError) as exc_info:
        await p.get_historical_bars("HPG", timeframe="1D")

    assert "transport error" in str(exc_info.value).lower()


async def test_empty_dataframe_returns_empty_bars_without_error():
    p, sess = _make_history_provider("empty")

    bars = await p.get_historical_bars("HPG", timeframe="1D")
    assert bars == []
    assert p.get_health()["historical_status"] == "HEALTHY"
    assert p.get_health()["historical_circuit_open"] is False
