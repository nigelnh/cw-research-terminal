"""Body-size caps, CORS, TrustedHost, security headers (Step 10 sections 8, 11, 12, 13, 28)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app

client = TestClient(app)


# --------------------------- body size ---------------------------

def test_oversized_json_body_is_413(monkeypatch):
    monkeypatch.setattr(settings, "API_MAX_BODY_BYTES", 512)
    big = {"discovered_symbols": ["SYM" + str(i) for i in range(500)]}
    r = client.post("/api/instruments/reconcile", json=big)
    assert r.status_code == 413
    assert r.json()["error"] == "payload_too_large"


def test_normal_small_json_body_is_accepted(monkeypatch):
    monkeypatch.setattr(settings, "API_MAX_BODY_BYTES", 64 * 1024)
    r = client.post(
        "/api/quant/calculate",
        json={"underlyingPrice": 30000, "strikePrice": 25000, "timeToMaturity": 0.5,
              "riskFreeRate": 0.05, "volatility": 0.3, "exerciseRatio": 2.0},
    )
    assert r.status_code == 200


def test_ai_endpoint_gets_a_larger_body_allowance(monkeypatch):
    monkeypatch.setattr(settings, "API_MAX_BODY_BYTES", 256)
    monkeypatch.setattr(settings, "AI_MAX_BODY_BYTES", 200_000)
    monkeypatch.setattr(settings, "AI_ENABLED", True)
    monkeypatch.setattr(settings, "AI_PUBLIC_ENABLED", True)
    # ~2KB body: over the 256B generic cap, under the AI cap -> not a 413
    body = {"messages": [{"role": "user", "content": "x" * 2000}], "stream": False}
    r = client.post("/api/ai/chat", json=body)
    assert r.status_code != 413


def test_body_limit_does_not_apply_to_get(monkeypatch):
    monkeypatch.setattr(settings, "API_MAX_BODY_BYTES", 1)
    assert client.get("/api/instruments").status_code != 413


# --------------------------- CORS ---------------------------

def test_allowed_dev_origin_gets_cors_header():
    r = client.get("/api/instruments", headers={"Origin": "http://localhost:5173"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_arbitrary_origin_is_not_reflected():
    r = client.get("/api/instruments", headers={"Origin": "https://evil.example.com"})
    assert r.headers.get("access-control-allow-origin") not in ("https://evil.example.com", "*")


def test_explicit_production_origins(monkeypatch):
    monkeypatch.setattr(settings, "CORS_ALLOWED_ORIGINS", "https://app.example.com,https://www.example.com")
    assert settings.cors_allowed_origins() == ["https://app.example.com", "https://www.example.com"]


def test_credentials_never_combined_with_wildcard():
    # the app never sets allow_origins=["*"]; cors_allowed_origins is always an explicit list
    assert "*" not in settings.cors_allowed_origins()


# --------------------------- TrustedHost ---------------------------

def test_bad_host_rejected_when_enforced(monkeypatch):
    monkeypatch.setattr(settings, "ALLOWED_HOSTS", "api.example.com")
    from starlette.middleware.trustedhost import TrustedHostMiddleware

    guarded = TestClient(
        TrustedHostMiddleware(app, allowed_hosts=settings.allowed_hosts()),
        headers={"host": "evil.example.com"},
    )
    assert guarded.get("/health").status_code == 400


def test_host_not_enforced_by_default():
    assert settings.allowed_hosts() == ["*"]


# --------------------------- security headers ---------------------------

def test_api_responses_carry_hardening_headers():
    r = client.get("/api/market/health")
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert r.headers.get("referrer-policy") == "no-referrer"
    assert r.headers.get("x-frame-options") == "DENY"


def test_me_responses_are_not_cached():
    r = client.get("/api/me/watchlist")  # 503 (auth not configured) but headers still apply
    assert r.headers.get("cache-control") == "no-store"


def test_hsts_only_when_enabled(monkeypatch):
    assert "strict-transport-security" not in {k.lower() for k in client.get("/health").headers}
    monkeypatch.setattr(settings, "SECURITY_HSTS_ENABLED", True)
    assert client.get("/health").headers.get("strict-transport-security", "").startswith("max-age=")
