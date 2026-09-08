from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.enrichment import repository as enrichment_repo
from app.market_data.market_router import get_stock_profiles
from app.market_data.market_subscription_manager import subscription_manager
from app.persistence import database as persistence_db


class _SessionContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_stock_profiles_entitlement_failure_falls_back_in_one_db_batch(monkeypatch):
    provider_call = AsyncMock(side_effect=RuntimeError("403 entitlement denied"))
    monkeypatch.setattr(subscription_manager.provider, "get_stock_profiles", provider_call)
    monkeypatch.setattr(persistence_db, "is_configured", lambda: True)
    monkeypatch.setattr(persistence_db, "get_sessionmaker", lambda: lambda: _SessionContext())
    persisted_call = AsyncMock(return_value={
        "HPG": SimpleNamespace(
            symbol="HPG", en_name="Hoa Phat Group", vn_name="Hoa Phat",
            exchange="hose", source="VNDIRECT",
        ),
    })
    monkeypatch.setattr(enrichment_repo, "get_company_profiles", persisted_call)

    result = await get_stock_profiles("HPG,FPT")

    assert [item["symbol"] for item in result["items"]] == ["FPT", "HPG"]
    assert result["items"][0]["availability"] == "UNAVAILABLE"
    assert result["items"][1] == {
        "symbol": "HPG",
        "name": "Hoa Phat Group",
        "short_name": None,
        "exchange": "HOSE",
        "source": "VNDIRECT",
        "availability": "AVAILABLE",
    }
    persisted_call.assert_awaited_once()
    assert persisted_call.await_args.args[1] == ["FPT", "HPG"]


@pytest.mark.asyncio
async def test_stock_profiles_merge_provider_and_persisted_fields(monkeypatch):
    monkeypatch.setattr(
        subscription_manager.provider,
        "get_stock_profiles",
        AsyncMock(return_value=[{
            "symbol": "HPG", "name": "Hoa Phat Group", "short_name": "HPG", "exchange": None,
        }]),
    )
    monkeypatch.setattr(persistence_db, "is_configured", lambda: True)
    monkeypatch.setattr(persistence_db, "get_sessionmaker", lambda: lambda: _SessionContext())
    monkeypatch.setattr(enrichment_repo, "get_company_profiles", AsyncMock(return_value={
        "HPG": SimpleNamespace(
            symbol="HPG", en_name="Persisted Name", vn_name=None,
            exchange="HOSE", source="VNDIRECT",
        ),
    }))

    item = (await get_stock_profiles("HPG"))["items"][0]

    assert item["name"] == "Hoa Phat Group"
    assert item["short_name"] == "HPG"
    assert item["exchange"] == "HOSE"
    assert item["source"] == "VNSTOCK+VNDIRECT"
    assert item["availability"] == "AVAILABLE"
