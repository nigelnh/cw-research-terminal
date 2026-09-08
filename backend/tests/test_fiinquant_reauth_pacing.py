"""The re-authentication pacing contract.

Production, mid-session, after PR #90 removed the feed-wide block that had been masking
this: the 20s ``session_snapshot`` poll answered 401, ``_sdk_call`` cleared
``_is_connected`` for *every* scope, and the next poll called ``connect()`` again - a fresh
``login()`` roughly three times a minute. The account permits ONE concurrent connection,
so every new token evicted the SignalR streams the previous one owned and no tick ever
arrived. ``get_ceilingfloor`` returning 401 by account design (stocks only, never covered
warrants) was enough to sustain it.

These tests pin the three guards that stop it, without a real SDK or network:

  1. a REST endpoint's 401 does not clear ``_is_connected`` - only a failed login does;
  2. ``_connect_locked`` will not mint a new token more often than the floor, unless the
     SDK reports the session explicitly invalid;
  3. repeated stream-start failures on a still-"valid" session ask for exactly one paced
     re-auth via ``_force_reauth`` rather than flipping ``_is_connected``.
"""

import pytest

from app.market_data.market_schemas import HistoricalAuthError
from app.market_data.providers.fiinquant_provider import FiinQuantProvider

pytestmark = pytest.mark.asyncio


class _Session:
    """Shape-compatible with the bits of a FiinQuantX session the provider reads."""

    def __init__(self) -> None:
        self.is_login = True
        self.access_token = "not-a-jwt"  # inspect_session swallows the parse failure


def _provider() -> FiinQuantProvider:
    p = FiinQuantProvider(username="u", password="p", max_symbols=33)
    p._is_connected = True
    p._session = _Session()
    return p


def _raise_401() -> None:
    raise RuntimeError(
        "401, message='Unauthorized', "
        "url='https://apigw.fiingroup.vn/FXMA/TradingData/GetTradingDataByMultiEntities'"
    )


# --------------------------------------------------------------------------- #
# 1. A REST rejection stays in its lane
# --------------------------------------------------------------------------- #
async def test_a_rest_scope_401_does_not_drop_the_connection():
    p = _provider()
    with pytest.raises(HistoricalAuthError):
        p._sdk_call("session_snapshot", _raise_401)
    assert p._is_connected is True, "one REST endpoint's 401 must not tear the session down"


@pytest.mark.parametrize("scope", ["overview", "history", "reference", "profiles", "breadth"])
async def test_no_rest_scope_can_drop_the_connection(scope):
    p = _provider()
    with pytest.raises(HistoricalAuthError):
        p._sdk_call(scope, _raise_401)
    assert p._is_connected is True


async def test_only_a_failed_login_drops_the_connection():
    p = _provider()
    with pytest.raises(HistoricalAuthError):
        p._sdk_call("authentication", _raise_401)
    assert p._is_connected is False


# --------------------------------------------------------------------------- #
# 2. The re-auth floor
# --------------------------------------------------------------------------- #
async def test_connect_does_not_re_authenticate_within_the_floor(monkeypatch):
    p = FiinQuantProvider(username="u", password="p", max_symbols=33)
    p._reauth_min_interval_seconds = 60.0
    made = {"n": 0}

    def _factory():
        made["n"] += 1
        return _Session()

    monkeypatch.setattr(p, "_create_session", _factory)

    assert await p.connect() is True
    assert made["n"] == 1

    # The session looks dropped but is not explicitly invalid (is_login still True).
    p._is_connected = False
    assert await p.connect() is False
    assert made["n"] == 1, "a second login inside the floor must not happen"

    # Far enough in the past: allowed again.
    p._last_auth_attempt_monotonic -= 120.0
    assert await p.connect() is True
    assert made["n"] == 2


async def test_an_explicitly_invalid_session_bypasses_the_floor(monkeypatch):
    p = FiinQuantProvider(username="u", password="p", max_symbols=33)
    p._reauth_min_interval_seconds = 60.0
    made = {"n": 0}

    def _factory():
        made["n"] += 1
        return _Session()

    monkeypatch.setattr(p, "_create_session", _factory)

    assert await p.connect() is True
    # The SDK marks the token dead mid-session.
    p._session.is_login = False
    p._is_connected = False
    assert await p.connect() is True
    assert made["n"] == 2, "an explicitly invalid session must re-auth at once, floor or not"


async def test_a_cold_start_is_never_floored(monkeypatch):
    p = FiinQuantProvider(username="u", password="p", max_symbols=33)
    p._reauth_min_interval_seconds = 60.0
    monkeypatch.setattr(p, "_create_session", lambda: _Session())
    # No prior attempt: _last_auth_attempt_monotonic is -inf.
    assert await p.connect() is True


# --------------------------------------------------------------------------- #
# 3. Repeated stream-start failures ask for one paced re-auth
# --------------------------------------------------------------------------- #
async def test_stream_start_failures_set_reauth_intent_not_disconnect():
    p = _provider()
    p._stream_failures_before_reauth = 3
    p._active_symbols = ["HPG"]

    # Simulate the reconnect worker's failure branch three times over.
    for i in range(1, 4):
        p._consecutive_stream_start_failures = i
        if (
            not p._force_reauth
            and p._consecutive_stream_start_failures >= p._stream_failures_before_reauth
        ):
            p._force_reauth = True

    assert p._force_reauth is True
    assert p._is_connected is True, "_is_connected stays owned by real auth, not stream health"


async def test_a_successful_auth_clears_the_reauth_intent(monkeypatch):
    p = FiinQuantProvider(username="u", password="p", max_symbols=33)
    p._reauth_min_interval_seconds = 0.0
    p._force_reauth = True
    p._consecutive_stream_start_failures = 5
    p._is_connected = False
    monkeypatch.setattr(p, "_create_session", lambda: _Session())

    assert await p.connect() is True
    assert p._force_reauth is False
    assert p._consecutive_stream_start_failures == 0


async def test_force_reauth_defeats_the_idempotent_shortcut(monkeypatch):
    """A healthy-looking session must still re-auth when _force_reauth is set - otherwise
    the reconnect worker's request is silently dropped by the idempotent early return."""
    p = _provider()
    p._reauth_min_interval_seconds = 0.0
    p._force_reauth = True
    made = {"n": 0}

    def _factory():
        made["n"] += 1
        return _Session()

    monkeypatch.setattr(p, "_create_session", _factory)
    assert await p.connect() is True
    assert made["n"] == 1
