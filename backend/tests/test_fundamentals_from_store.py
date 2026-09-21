"""Fundamentals are served from Postgres, not fetched on the request.

Production could not fetch them at all. Railway's egress (AS400940, Amsterdam) is answered
with HTTP 403 on Vietcap's VCI GraphQL fundamentals query, while the identical library
version and query succeed from a university network (AS11231) and from a GitHub-hosted
runner (Azure, AS8075) - probed from inside the production container on 2026-09-21. So
`/api/market/fundamentals/{symbol}` answered pe, pb, eps, roe and roa all null for every
equity, with `quarters: []`, and nothing cached the rejection so every page view tried again.

These pin the read path only: the store answers when it can, the provider is the fallback,
and a persistence fault degrades instead of 500-ing an endpoint whose contract is to answer
partially.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

OBSERVED = datetime(2026, 9, 21, 3, 0, tzinfo=timezone.utc)

STORED = SimpleNamespace(
    symbol="HPG",
    valuation={"symbol": "HPG", "pe": 7.9, "pb": 1.3, "as_of": "2026Q2"},
    quarters=[{
        "period": "2026Q2", "eps": 1781, "roe": 0.21, "roa": 0.12, "roic": 0.18,
        "gross_margin": 0.24, "net_margin": 0.115, "revenue": 55_000, "net_profit": 6_300,
        "ratio_source": "VNSTOCK_VCI_RATIO_SUMMARY",
        "statement_source": "VNSTOCK_VCI_INCOME_STATEMENT",
    }],
    source="VNSTOCK_VCI",
    observed_at=OBSERVED,
)


@asynccontextmanager
async def _session():
    yield object()


def _with_store(row):
    """Patch the persistence boundary, not the function under test, so
    `_stored_fundamentals` itself is exercised."""
    maker = lambda: _session()  # noqa: E731 - a sessionmaker is called, not awaited
    return (
        patch("app.market_data.market_router.persistence_db.is_configured", return_value=True),
        patch("app.market_data.market_router.persistence_db.get_sessionmaker", return_value=maker),
        patch(
            "app.market_data.market_router.fundamentals_repository.get_fundamentals",
            new=AsyncMock(return_value=row),
        ),
    )


def test_a_stored_row_is_served_without_touching_the_provider():
    valuation_call = AsyncMock()
    ratios_call = AsyncMock()
    a, b, c = _with_store(STORED)
    with a, b, c, \
         patch("app.market_data.market_router.subscription_manager.provider.get_stock_valuation", valuation_call), \
         patch("app.market_data.market_router.subscription_manager.provider.get_financial_ratios", ratios_call), \
         TestClient(app) as client:
        body = client.get("/api/market/fundamentals/HPG").json()

    assert body["pe"] == 7.9 and body["pb"] == 1.3
    assert body["eps"] == 1781 and body["roe"] == 0.21
    assert body["latest_period"] == "2026Q2"
    assert body["served_from"] == "store"
    assert body["observed_at"] == OBSERVED.isoformat()
    assert body["errors"] == []
    assert body["unavailable"] == {}
    valuation_call.assert_not_awaited()
    ratios_call.assert_not_awaited()


def test_an_empty_store_falls_back_to_the_provider():
    a, b, c = _with_store(None)
    with a, b, c, \
         patch("app.market_data.market_router.subscription_manager.provider.get_stock_valuation",
               new=AsyncMock(return_value={"HPG": {"pe": 8.1, "pb": 1.4, "as_of": "2026Q2"}})), \
         patch("app.market_data.market_router.subscription_manager.provider.get_financial_ratios",
               new=AsyncMock(return_value=[{"period": "2026Q2", "roe": 0.2}])), \
         TestClient(app) as client:
        body = client.get("/api/market/fundamentals/HPG").json()

    assert body["served_from"] == "provider"
    assert body["pe"] == 8.1
    assert body["observed_at"] is None


def test_a_row_with_nothing_in_it_is_not_an_answer():
    """An empty row must not shadow the provider - that is how a bad ingestion run would
    replace a working answer with nulls."""
    empty = SimpleNamespace(symbol="HPG", valuation={}, quarters=[],
                            source="VNSTOCK_VCI", observed_at=OBSERVED)
    a, b, c = _with_store(empty)
    with a, b, c, \
         patch("app.market_data.market_router.subscription_manager.provider.get_stock_valuation",
               new=AsyncMock(return_value={"HPG": {"pe": 8.1, "pb": 1.4}})), \
         patch("app.market_data.market_router.subscription_manager.provider.get_financial_ratios",
               new=AsyncMock(return_value=[])), \
         TestClient(app) as client:
        body = client.get("/api/market/fundamentals/HPG").json()

    assert body["served_from"] == "provider"
    assert body["pe"] == 8.1


def test_a_persistence_fault_degrades_instead_of_500ing():
    with patch("app.market_data.market_router.persistence_db.is_configured", return_value=True), \
         patch("app.market_data.market_router.persistence_db.get_sessionmaker",
               side_effect=RuntimeError("pool exhausted")), \
         patch("app.market_data.market_router.subscription_manager.provider.get_stock_valuation",
               new=AsyncMock(return_value={"HPG": {"pe": 8.1}})), \
         patch("app.market_data.market_router.subscription_manager.provider.get_financial_ratios",
               new=AsyncMock(return_value=[])), \
         TestClient(app) as client:
        response = client.get("/api/market/fundamentals/HPG")

    assert response.status_code == 200
    assert response.json()["served_from"] == "provider"


def test_the_endpoint_still_answers_when_both_layers_are_empty():
    """The pre-fix production shape. It must stay a named partial answer, not a 500."""
    a, b, c = _with_store(None)
    with a, b, c, \
         patch("app.market_data.market_router.subscription_manager.provider.get_stock_valuation",
               new=AsyncMock(side_effect=RuntimeError("403 - Forbidden"))), \
         patch("app.market_data.market_router.subscription_manager.provider.get_financial_ratios",
               new=AsyncMock(side_effect=RuntimeError("403 - Forbidden"))), \
         TestClient(app) as client:
        response = client.get("/api/market/fundamentals/HPG")

    body = response.json()
    assert response.status_code == 200
    assert body["errors"] == ["valuation", "ratios"]
    assert set(body["unavailable"]) == {"eps", "roe", "roa", "roic", "gross_margin"}


# --------------------------------------------------------------------------- #
# The write path. Production cannot fetch fundamentals (Railway's ASN is 403'd by
# Vietcap) and the GitHub runner that CAN fetch them cannot reach Railway Postgres
# (no public TCP proxy, `*.railway.internal` only). So the rows arrive over HTTP on
# an authenticated write-only route and the backend does the insert privately.
# --------------------------------------------------------------------------- #
INGEST = "/api/market/fundamentals/ingest"
GOOD_ITEM = {"symbol": "HPG", "valuation": {"pe": 7.9, "pb": 1.3},
             "quarters": [{"period": "2026Q2", "roe": 0.21}]}


class _FakeSession:
    def __init__(self, sink): self.sink = sink
    async def __aenter__(self): return self
    async def __aexit__(self, *exc): return False
    async def commit(self): self.sink["committed"] = True


def _writable_db(sink):
    return (
        patch("app.market_data.market_router.persistence_db.is_configured", return_value=True),
        patch("app.market_data.market_router.persistence_db.get_sessionmaker",
              return_value=lambda: _FakeSession(sink)),
        patch("app.market_data.market_router.fundamentals_repository.upsert_fundamentals",
              new=AsyncMock(side_effect=lambda *a, **kw: sink.setdefault("rows", []).append(kw))),
    )


def _token(value):
    return patch("app.security.ingest_token.settings.FUNDAMENTALS_INGEST_TOKEN", value)


def test_an_unconfigured_token_disables_the_route_entirely():
    """Fails closed. A deployment that forgot to set the token must not leave an
    unauthenticated write open."""
    with _token(""), TestClient(app) as client:
        r = client.post(INGEST, json={"items": [GOOD_ITEM]},
                        headers={"Authorization": "Bearer anything"})
    assert r.status_code == 503
    assert r.json()["detail"]["reason"] == "ingest_token_not_configured"


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer wrong-token"}, {"Authorization": "Basic secret-token"}],
    ids=["no-header", "wrong-token", "wrong-scheme"],
)
def test_only_the_configured_bearer_token_is_accepted(headers):
    with _token("secret-token"), TestClient(app) as client:
        r = client.post(INGEST, json={"items": [GOOD_ITEM]}, headers=headers)
    assert r.status_code == 401
    # The presented token must never be echoed back to the caller.
    assert "wrong-token" not in r.text and "secret-token" not in r.text


def test_a_valid_token_persists_every_item():
    sink: dict = {}
    a, b, c = _writable_db(sink)
    with _token("secret-token"), a, b, c, TestClient(app) as client:
        r = client.post(
            INGEST,
            json={"items": [GOOD_ITEM, {"symbol": "vpb", "valuation": {"pe": 9.0}, "quarters": []}]},
            headers={"Authorization": "Bearer secret-token"},
        )
    body = r.json()
    assert r.status_code == 200
    assert body["written"] == ["HPG", "VPB"]  # symbol is normalised upward
    assert body["count"] == 2
    assert sink["committed"] is True
    assert [row["symbol"] for row in sink["rows"]] == ["HPG", "VPB"]


def test_an_item_with_no_fundamentals_is_refused_before_it_can_overwrite():
    """The exact shape a failed upstream fetch produces. Accepting it would replace a good
    stored row with the nulls this whole pipeline exists to end."""
    sink: dict = {}
    a, b, c = _writable_db(sink)
    with _token("secret-token"), a, b, c, TestClient(app) as client:
        r = client.post(
            INGEST,
            json={"items": [{"symbol": "HPG", "valuation": {}, "quarters": []}]},
            headers={"Authorization": "Bearer secret-token"},
        )
    assert r.status_code == 422
    assert "rows" not in sink  # nothing reached the database


def test_ingest_without_a_database_reports_that_rather_than_silently_succeeding():
    with _token("secret-token"), \
         patch("app.market_data.market_router.persistence_db.is_configured", return_value=False), \
         TestClient(app) as client:
        r = client.post(INGEST, json={"items": [GOOD_ITEM]},
                        headers={"Authorization": "Bearer secret-token"})
    assert r.status_code == 503
    assert r.json()["detail"]["reason"] == "database_not_configured"
