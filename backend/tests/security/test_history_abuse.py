"""History endpoint - HTTP-layer provider-quota protection (Step 10 sections 6, 26).

The DB-hit-is-zero-provider and single-flight guarantees are Step-7 behavior and are
covered under tests/persistence/ingestion/. Here we prove the NEW HTTP layer:
a rate-limited request never reaches the provider.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.market_data.market_schemas import HistoricalBar
from app.market_data.market_subscription_manager import subscription_manager
from app.security.policies import policy_table

client = TestClient(app)


def _bar(d: str) -> HistoricalBar:
    return HistoricalBar(date=d, open=1.0, high=1.0, low=1.0, close=1.0, volume=1, adjusted=True)


@pytest.fixture
def tight_history_limit(rate_limit_enabled, monkeypatch):
    monkeypatch.setattr(settings, "RL_HISTORY_PER_MIN", 2)
    policy_table.cache_clear()
    yield
    policy_table.cache_clear()


def test_rate_limited_history_request_never_calls_the_provider(tight_history_limit):
    with patch.object(subscription_manager.provider, "get_historical_bars", new_callable=AsyncMock) as prov:
        prov.return_value = [_bar("2026-08-20"), _bar("2026-08-21")]

        r1 = client.get("/api/market/history/HPG?timeframe=1D")
        r2 = client.get("/api/market/history/HPG?timeframe=1D")
        assert r1.status_code == 200 and r2.status_code == 200
        calls_after_ok = prov.await_count

        blocked = client.get("/api/market/history/HPG?timeframe=1D")
        assert blocked.status_code == 429
        assert blocked.headers.get("retry-after") is not None
        # the rejected request did NOT reach the provider
        assert prov.await_count == calls_after_ok


def test_history_span_and_row_caps_are_still_enforced():
    # HISTORY_MAX_RANGE_DAYS default ~1500; a 10-year span must 400 regardless of limiter
    r = client.get("/api/market/history/HPG?timeframe=1D&from_date=2015-01-01&to_date=2026-08-27")
    assert r.status_code == 400


def test_unknown_symbol_is_not_a_provider_oracle():
    """A bogus symbol still goes provider-direct (no PG), but the provider itself
    returns nothing and the response is a clean empty list - not an error, not a probe loop."""
    with patch.object(subscription_manager.provider, "get_historical_bars", new_callable=AsyncMock) as prov:
        prov.return_value = []
        r = client.get("/api/market/history/NOTREAL9?timeframe=1D")
        assert r.status_code == 200
        assert r.json() == []
