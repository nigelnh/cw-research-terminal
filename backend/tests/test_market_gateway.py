import json
import pytest
import asyncio
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.market_data.market_state import MarketState
from app.market_data.market_subscription_manager import SubscriptionManager
from app.market_data.providers.fiinquant_provider import FiinQuantProvider
from tests.fixtures.mock_market_provider import MockMarketDataProvider
from app.market_data.market_schemas import CanonicalQuote, HistoricalBar

client = TestClient(app)


def test_subscription_manager_defaults_to_live_fiinquant():
    mgr = SubscriptionManager()
    assert isinstance(mgr.provider, FiinQuantProvider)


def test_production_providers_package_contains_no_mock():
    import app.market_data.providers as prov_pkg
    assert not hasattr(prov_pkg, "MockMarketDataProvider")
    assert "MockMarketDataProvider" not in prov_pkg.__all__


def test_market_state_trade_normalization():
    state = MarketState()
    raw_trade = {
        "Ticker": "HPG",
        "Close": 22150.0,
        "ReferencePrice": 22250.0,
        "change": -100.0,
        "ChangePercent": -0.45,
        "TotalMatchVolume": 1056600,
        "TradingDate": "2026-08-25T09:28:23.538+07:00",
        "Timestamp": "2026-08-25T09:28:23",
    }

    quote, diff = state.apply_trade_event(raw_trade)
    assert quote.symbol == "HPG"
    assert quote.instrument_type == "STOCK"
    assert quote.last_price == 22150.0
    assert quote.reference_price == 22250.0
    assert quote.total_volume == 1056600
    assert diff["last_price"] == 22150.0

    wire_row = quote.to_wire_snapshot_row()
    assert wire_row["Symbol"] == "HPG"
    # Frontend mapper multiplies Traded by 1000, so wire is 22.15
    assert wire_row["Traded"] == 22.15
    assert wire_row["Total_Vol"] == 1056600


def test_market_state_bidask_normalization_and_merge():
    state = MarketState()
    raw_ba = {
        "Ticker": "CHPG2602",
        "Best1Bid": 50.0,
        "Best1BidVolume": 900,
        "Best1Ask": 60.0,
        "Best1AskVolume": 10000,
        "Timestamp": "2026-08-25T09:28:40",
    }

    quote, diff = state.apply_bidask_event(raw_ba)
    assert quote.symbol == "CHPG2602"
    assert quote.instrument_type == "CW"
    assert quote.bid1_price == 50.0
    assert quote.bid1_quantity == 900
    assert quote.ask1_price == 60.0
    assert quote.ask1_quantity == 10000
    # Crucial assertion: last_price remains None if no trade occurred
    assert quote.last_price is None

    wire_row = quote.to_wire_snapshot_row()
    assert wire_row["Symbol"] == "CHPG2602"
    assert wire_row["Bid1_Prc"] == 0.05
    assert wire_row["Ask1_Prc"] == 0.06
    assert wire_row["Traded"] is None

    # Now apply a trade to the same symbol to test merge
    raw_trade = {
        "Ticker": "CHPG2602",
        "Close": 55.0,
        "TotalMatchVolume": 5000,
    }
    merged_quote, diff_trade = state.apply_trade_event(raw_trade)
    assert merged_quote.symbol == "CHPG2602"
    assert merged_quote.last_price == 55.0
    assert merged_quote.bid1_price == 50.0
    assert merged_quote.ask1_price == 60.0


def test_subscription_manager_capacity_and_deduplication():
    mock_prov = MockMarketDataProvider(max_symbols=5)
    mock_state = MarketState()
    mgr = SubscriptionManager(provider=mock_prov, state=mock_state, max_symbols=5, debounce_ms=10)

    # 1. Deduplicate symbols
    success, msg = mgr.subscribe(["hpg", "HPG", "chpg2602"])
    assert success is True
    assert mgr.get_desired_symbols() == ["CHPG2602", "HPG"]

    # 2. Add more within capacity
    success, msg = mgr.subscribe(["FPT", "VNINDEX"])
    assert success is True
    assert len(mgr.get_desired_symbols()) == 4

    # 3. Exceed capacity (4 + 2 = 6 > 5)
    success, msg = mgr.subscribe(["MWG", "VIC"])
    assert success is False
    assert "exceeds capacity limit" in msg
    # Desired set remains untouched at 4
    assert len(mgr.get_desired_symbols()) == 4

    # 4. Unsubscribe
    mgr.unsubscribe(["FPT"])
    assert mgr.get_desired_symbols() == ["CHPG2602", "HPG", "VNINDEX"]


@pytest.mark.asyncio
async def test_subscription_manager_debounced_restart():
    mock_prov = MockMarketDataProvider(max_symbols=10)
    mock_state = MarketState()
    mgr = SubscriptionManager(provider=mock_prov, state=mock_state, max_symbols=10, debounce_ms=50)

    # Rapid calls
    mgr.subscribe(["HPG"])
    mgr.subscribe(["CHPG2602"])
    mgr.subscribe(["VNINDEX"])

    # Wait for debounce window to fire
    await asyncio.sleep(0.1)
    assert set(mock_prov.get_active_subscriptions()) == {"HPG", "CHPG2602", "VNINDEX"}


def test_market_rest_health_zero_credentials():
    response = client.get("/api/market/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "max_subscriptions" in data
    # Verify no secret keywords exist in health payload
    assert "password" not in json.dumps(data).lower()
    assert "token" not in json.dumps(data).lower()


def test_market_rest_history():
    from unittest.mock import AsyncMock, patch
    from app.market_data.market_subscription_manager import subscription_manager

    fake_bars = [
        HistoricalBar(date="2026-08-25", open=22000.0, high=22500.0, low=21900.0, close=22150.0, volume=1050000.0, adjusted=True)
    ]
    with patch.object(subscription_manager.provider, "get_historical_bars", new_callable=AsyncMock) as mock_hist:
        mock_hist.return_value = fake_bars
        response = client.get("/api/market/history/HPG?timeframe=1D&adjusted=true")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 1
        bar = data[0]
        assert bar["date"] == "2026-08-25"
        assert bar["open"] == 22000.0
        assert bar["close"] == 22150.0
        assert bar["volume"] == 1050000.0


def test_websocket_gateway_protocol():
    with client.websocket_connect("/ws/market") as ws:
        # 1. Verify initial status frame
        init_raw = ws.receive_text()
        init_data = json.loads(init_raw)
        assert init_data["type"] == "status"

        # 2. Send subscribe control message
        ws.send_text(json.dumps({"type": "subscribe", "symbols": ["HPG", "CHPG2602"]}))

        # Wait small tick or verify receive
        ws.send_text(json.dumps({"type": "unsubscribe", "symbols": ["CHPG2602"]}))
