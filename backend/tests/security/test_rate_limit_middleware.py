"""RateLimitMiddleware end-to-end (Step 10 sections 22, 25, 29)."""

from __future__ import annotations

import time

import jwt
import pytest
from fastapi.testclient import TestClient

from app.auth.jwt_verifier import get_verifier
from app.core.config import settings
from app.main import app
from app.security.policies import policy_table

client = TestClient(app)


@pytest.fixture
def low_market_limit(rate_limit_enabled, monkeypatch):
    monkeypatch.setattr(settings, "RL_MARKET_PER_MIN", 3)
    policy_table.cache_clear()
    yield
    policy_table.cache_clear()


def test_excess_requests_get_429_with_retry_after(low_market_limit):
    # instruments list is Tier B (market)
    ok = [client.get("/api/instruments") for _ in range(3)]
    assert all(r.status_code != 429 for r in ok)

    blocked = client.get("/api/instruments")
    assert blocked.status_code == 429
    body = blocked.json()
    assert body["error"] == "rate_limited"
    assert body["tier"] == "market"
    assert "detail" in body and "key" not in body
    ra = blocked.headers.get("retry-after")
    assert ra is not None and int(ra) >= 1


def test_options_preflight_is_never_rate_limited(low_market_limit):
    for _ in range(10):
        r = client.options(
            "/api/instruments",
            headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
        )
        assert r.status_code != 429


def test_spoofed_xff_cannot_split_the_limiter_bucket(low_market_limit, monkeypatch):
    # trust proxy is OFF by default -> the forged header must not create a fresh bucket
    for i in range(3):
        assert client.get("/api/instruments", headers={"x-forwarded-for": f"9.9.9.{i}"}).status_code != 429
    blocked = client.get("/api/instruments", headers={"x-forwarded-for": "9.9.9.99"})
    assert blocked.status_code == 429


def test_health_tier_is_generous(rate_limit_enabled, monkeypatch):
    monkeypatch.setattr(settings, "RL_HEALTH_PER_MIN", 50)
    policy_table.cache_clear()
    codes = {client.get("/health").status_code for _ in range(30)}
    assert 429 not in codes
    policy_table.cache_clear()


def test_disabled_switch_removes_all_limits(monkeypatch):
    monkeypatch.setattr(settings, "PUBLIC_RATE_LIMIT_ENABLED", False)
    monkeypatch.setattr(settings, "RL_MARKET_PER_MIN", 1)
    policy_table.cache_clear()
    codes = {client.get("/api/instruments").status_code for _ in range(10)}
    assert 429 not in codes


def test_429_carries_cors_header_for_an_allowed_origin(low_market_limit):
    for _ in range(3):
        client.get("/api/instruments", headers={"Origin": "http://localhost:5173"})
    blocked = client.get("/api/instruments", headers={"Origin": "http://localhost:5173"})
    assert blocked.status_code == 429
    assert blocked.headers.get("access-control-allow-origin") == "http://localhost:5173"


# --- AI tier: guest vs signed-in allowances (subject_or_ip) -----------------

_AI_TEST_SECRET = "ai-tier-test-hs256-secret-at-least-32-bytes+"
_AI_BODY = {"messages": [{"role": "user", "content": "hi"}], "stream": False}


def _ai_token(*, sub: str) -> str:
    now = int(time.time())
    return jwt.encode(
        {"sub": sub, "aud": "authenticated", "iat": now - 5, "exp": now + 3600},
        _AI_TEST_SECRET, algorithm="HS256",
    )


@pytest.fixture
def ai_tier_limits(rate_limit_enabled, monkeypatch):
    """Tiny, deterministic guest vs signed-in AI allowances for one test, plus a working
    test-only HS256 secret so a minted bearer token verifies as a real signed-in caller."""
    monkeypatch.setattr(settings, "RL_AI_GUEST_PER_MIN", 1)
    monkeypatch.setattr(settings, "RL_AI_GUEST_PER_DAY", 100)
    monkeypatch.setattr(settings, "RL_AI_AUTH_PER_MIN", 3)
    monkeypatch.setattr(settings, "RL_AI_AUTH_PER_DAY", 100)
    monkeypatch.setattr(settings, "AUTH_TEST_HS256_SECRET", _AI_TEST_SECRET)
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    policy_table.cache_clear()
    get_verifier.cache_clear()
    yield
    policy_table.cache_clear()
    get_verifier.cache_clear()


def test_ai_tier_guest_and_signed_in_get_independent_allowances(ai_tier_limits):
    # Guest (anonymous, IP-keyed): allowed exactly RL_AI_GUEST_PER_MIN=1, then 429.
    first = client.post("/api/ai/chat", json=_AI_BODY)
    assert first.status_code != 429
    second = client.post("/api/ai/chat", json=_AI_BODY)
    assert second.status_code == 429
    assert second.json()["tier"] == "ai"

    # Signed-in (subject-keyed): a SEPARATE bucket with its own, larger allowance - not
    # blocked by the guest bucket above already being exhausted.
    headers = {"Authorization": f"Bearer {_ai_token(sub='11111111-1111-1111-1111-111111111111')}"}
    for _ in range(3):
        r = client.post("/api/ai/chat", json=_AI_BODY, headers=headers)
        assert r.status_code != 429
    blocked = client.post("/api/ai/chat", json=_AI_BODY, headers=headers)
    assert blocked.status_code == 429


def test_ai_tier_invalid_token_falls_back_to_the_guest_allowance(ai_tier_limits):
    """`_peek_verified_subject`'s documented contract: any verification failure keys
    anonymous (ip), never raises here - the route still returns its own 401 if it cares."""
    headers = {"Authorization": "Bearer not-a-real-jwt"}
    first = client.post("/api/ai/chat", json=_AI_BODY, headers=headers)
    assert first.status_code != 429
    second = client.post("/api/ai/chat", json=_AI_BODY, headers=headers)
    assert second.status_code == 429  # the guest (1/min) allowance, not the signed-in one


def test_ai_quota_reports_the_guest_allowance_and_tracks_usage(ai_tier_limits):
    q0 = client.get("/api/ai/quota").json()
    assert q0["enabled"] is True and q0["tier"] == "guest"
    assert q0["per_day"]["limit"] == 100 and q0["per_day"]["used"] == 0
    assert q0["per_minute"]["limit"] == 1

    # a chat request is consumed by the rate-limit middleware even when the route then
    # fails (AI disabled in tests) - the quota read must reflect it.
    client.post("/api/ai/chat", json=_AI_BODY)
    q1 = client.get("/api/ai/quota").json()
    assert q1["per_day"]["used"] == 1 and q1["per_day"]["remaining"] == 99
    assert q1["per_minute"]["used"] == 1


def test_ai_quota_reports_the_signed_in_allowance(ai_tier_limits):
    headers = {"Authorization": f"Bearer {_ai_token(sub='22222222-2222-2222-2222-222222222222')}"}
    q = client.get("/api/ai/quota", headers=headers).json()
    assert q["tier"] == "authenticated"
    assert q["per_day"]["limit"] == 100  # RL_AI_AUTH_PER_DAY
    assert q["per_minute"]["limit"] == 3  # RL_AI_AUTH_PER_MIN, not the guest 1


def test_ai_quota_says_disabled_when_rate_limiting_is_off(monkeypatch):
    monkeypatch.setattr(settings, "PUBLIC_RATE_LIMIT_ENABLED", False)
    q = client.get("/api/ai/quota").json()
    assert q["enabled"] is False
