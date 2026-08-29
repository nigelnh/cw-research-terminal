"""The recruiter path stays frictionless (Step 10 section 29) + /health observability (21)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.market_data.market_subscription_manager import subscription_manager

client = TestClient(app)


def test_anonymous_can_use_the_core_product_with_default_limits(rate_limit_enabled):
    """Rate limiting ON with production defaults - an ordinary first-visit burst must not 429.
    The provider is mocked so a real upstream 429 (a different concern) can't confuse this."""
    assert client.get("/health").status_code == 200
    assert client.get("/api/market/health").status_code == 200
    assert client.get("/api/instruments").status_code == 200
    for sym in ("HPG", "VHM", "FPT", "MWG"):
        assert client.get(f"/api/market/quote/{sym}").status_code in (200, 404)  # 404 = no cached quote, still not 429
    with patch.object(subscription_manager.provider, "get_historical_bars", new_callable=AsyncMock) as prov:
        prov.return_value = []
        for _ in range(5):
            assert client.get("/api/market/history/HPG?timeframe=1D").status_code == 200
    for _ in range(6):
        r = client.post("/api/quant/calculate", json={
            "underlyingPrice": 30000, "strikePrice": 25000, "timeToMaturity": 0.4,
            "riskFreeRate": 0.05, "volatility": 0.3, "exerciseRatio": 2.0,
        })
        assert r.status_code == 200
    # nothing in that sequence tripped a limit
    # (defaults: market 120/min, history 20/min, quant 40/min)


def test_websocket_connects_anonymously(rate_limit_enabled):
    with client.websocket_connect("/ws/market") as ws:
        assert json.loads(ws.receive_text())["type"] == "status"


def test_no_auth_required_anywhere_public():
    for path in ("/health", "/api/market/health", "/api/instruments",
                 "/api/instruments/meta/underlyings", "/api/quant/CHPG2602"):
        assert client.get(path).status_code not in (401, 403)


def test_health_reports_protection_state():
    body = client.get("/health").json()
    sec = body["security"]
    assert "rate_limit" in sec and "backend" in sec["rate_limit"]
    assert set(sec["gates"]) == {"ai_calls", "history_gapfill"}
    assert "ws" in sec and "active" in sec["ws"]
    assert "counters" in sec
    # no sensitive material
    dumped = json.dumps(body)
    assert "OPENROUTER_API_KEY" not in dumped
    for secret_ish in (settings.OPENROUTER_API_KEY, settings.SUPABASE_JWT_SECRET, settings.FIINQUANT_PASSWORD):
        if secret_ish:
            assert secret_ish not in dumped


def test_health_counters_increment_on_rejection(rate_limit_enabled, monkeypatch):
    monkeypatch.setattr(settings, "RL_MARKET_PER_MIN", 1)
    from app.security.policies import policy_table

    policy_table.cache_clear()
    client.get("/api/instruments")
    client.get("/api/instruments")  # 429
    counters = client.get("/health").json()["security"]["counters"]["counters"]
    assert counters.get("rate_limit.rejected_total", 0) >= 1
    policy_table.cache_clear()
