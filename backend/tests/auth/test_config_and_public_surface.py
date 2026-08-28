"""Auth config guards + proof the auth router did not become global protection."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app

client = TestClient(app)


# --- the test-only HS256 hatch must be impossible to use in production -------

def test_test_hs256_secret_is_ignored_in_production(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_TEST_HS256_SECRET", "some-dev-secret-value-32-bytes-minimum!!")
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    assert settings.auth_test_secret_active() == ""

    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    assert settings.auth_test_secret_active() == "some-dev-secret-value-32-bytes-minimum!!"


def test_auth_configured_reflects_settings(monkeypatch):
    monkeypatch.setattr(settings, "SUPABASE_URL", "")
    monkeypatch.setattr(settings, "SUPABASE_JWT_SECRET", "")
    assert settings.auth_configured() is False
    monkeypatch.setattr(settings, "SUPABASE_URL", "https://abc.supabase.co")
    assert settings.auth_configured() is True
    assert settings.supabase_issuer() == "https://abc.supabase.co/auth/v1"
    assert settings.supabase_jwks_url().endswith("/auth/v1/.well-known/jwks.json")


# --- public surface stays anonymous (Section 21) ---------------------------

def test_health_is_public():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert "auth" in r.json()


def test_market_history_is_public():
    # 200 (mock provider) or an upstream/data status - never 401/403.
    r = client.get("/api/market/history/HPG", params={"timeframe": "1D"})
    assert r.status_code not in (401, 403)


def test_market_health_is_public():
    r = client.get("/api/market/health")
    assert r.status_code == 200


def test_quant_calculate_is_public():
    r = client.post(
        "/api/quant/calculate",
        json={
            "underlyingPrice": 30000,
            "strikePrice": 25000,
            "timeToMaturity": 0.5,
            "riskFreeRate": 0.05,
            "volatility": 0.3,
            "optionType": "call",
        },
    )
    assert r.status_code not in (401, 403)


def test_instruments_list_is_public():
    r = client.get("/api/instruments")
    assert r.status_code not in (401, 403)


@pytest.mark.parametrize("path", ["/api/me/watchlist"])
def test_me_namespace_is_the_only_protected_one(path):
    # With no auth configured in the default test settings, /api/me answers 503 (config),
    # and every public path above answers non-401/403. This asserts protection is scoped.
    r = client.get(path)
    assert r.status_code in (401, 503)
