"""RateLimitMiddleware end-to-end (Step 10 sections 22, 25, 29)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

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
