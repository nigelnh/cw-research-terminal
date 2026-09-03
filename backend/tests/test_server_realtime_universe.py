"""Server-owned realtime universe and per-client WebSocket delivery semantics."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.instruments.instrument_registry import InstrumentRegistry
from app.instruments.instrument_schemas import InstrumentLifecycleStatus
from app.instruments.providers.canonical_provider import CanonicalInstrumentProvider
from app.instruments.research_universe import (
    EXPECTED_UNIVERSE_SIZE,
    resolve_default_research_universe,
)
from app.main import app
from app.market_data.market_state import MarketState, market_state
from app.market_data.market_state_store import NullMarketStateStore
from app.market_data.market_subscription_manager import SubscriptionManager, subscription_manager
from app.market_data.market_websocket import manager
from app.market_data.session_reference import reference_session_date
from tests.fixtures.mock_market_provider import MockMarketDataProvider


client = TestClient(app)


async def _resolved_default():
    registry = InstrumentRegistry(CanonicalInstrumentProvider())
    await registry.initialize(current_date="2026-09-02")
    universe = await resolve_default_research_universe(registry, today="2026-09-02")
    return registry, universe


@pytest.mark.asyncio
async def test_default_realtime_universe_is_exact_and_has_no_index():
    _, universe = await _resolved_default()

    assert universe.complete is True
    assert len(universe.symbols) == EXPECTED_UNIVERSE_SIZE == 30
    assert universe.stock_count == 3
    assert universe.covered_warrant_count == 27
    assert "VNINDEX" not in universe.symbols
    assert universe.health()["status"] == "OK"


@pytest.mark.asyncio
async def test_invalid_cw_is_withheld_without_replacement(tmp_path: Path):
    registry, _ = await _resolved_default()
    invalid_symbol = "CHPG2617"
    registry._instruments[invalid_symbol] = registry._instruments[invalid_symbol].model_copy(
        update={"status": InstrumentLifecycleStatus.EXPIRED}
    )

    source = Path(__file__).parents[1] / "app/instruments/data/default_research_universe.json"
    copied = tmp_path / "default_research_universe.json"
    copied.write_text(source.read_text())
    universe = await resolve_default_research_universe(
        registry, path=copied, today="2026-09-02"
    )

    assert invalid_symbol not in universe.symbols
    assert len(universe.symbols) == 29
    assert universe.complete is False
    assert universe.health()["status"] == "DEGRADED"
    assert any(
        issue.symbol == invalid_symbol and "lifecycle_expired" in issue.reason
        for issue in universe.issues
    )


@pytest.mark.asyncio
async def test_manager_activates_server_universe_once_at_startup_and_rejects_mutation():
    _, universe = await _resolved_default()
    provider = MockMarketDataProvider(max_symbols=33)
    managed = SubscriptionManager(
        provider=provider,
        state=MarketState(),
        store=NullMarketStateStore(),
        max_symbols=33,
    )

    configured, _ = managed.configure_server_universe(universe)
    assert configured is True
    assert await managed.initialize() is True
    assert set(provider.get_active_subscriptions()) == set(universe.symbols)
    assert managed.get_universe_health()["active_complete"] is True

    before = managed.get_desired_symbols()
    assert managed.set_exact_subscriptions(["HPG"])[0] is False
    assert managed.subscribe(["VNINDEX"])[0] is False
    managed.unsubscribe(["FPT"])
    assert managed.get_desired_symbols() == before
    assert "VNINDEX" not in managed.get_active_symbols()
    await managed.shutdown()


@pytest.mark.asyncio
async def test_startup_refreshes_reference_metadata_before_opening_streams():
    _, universe = await _resolved_default()

    class OrderedProvider(MockMarketDataProvider):
        def __init__(self):
            super().__init__(max_symbols=33)
            self.events: list[str] = []

        async def connect(self) -> bool:
            self.events.append("connect")
            return await super().connect()

        async def get_session_reference_data(self, symbols, session_date):
            self.events.append("reference")
            return {
                symbol: {
                    "session_date": session_date.isoformat(),
                    "reference_price": 22_100.0,
                    "ceiling_price": 23_600.0,
                    "floor_price": 20_600.0,
                }
                for symbol in symbols
            }

        async def set_subscriptions(self, symbols):
            self.events.append("subscribe")
            return await super().set_subscriptions(symbols)

    provider = OrderedProvider()
    state = MarketState()
    managed = SubscriptionManager(
        provider=provider,
        state=state,
        store=NullMarketStateStore(),
        max_symbols=33,
    )
    patches: list[dict] = []
    managed.register_patch_listener(patches.append)
    managed.configure_server_universe(universe)

    assert await managed.initialize() is True
    assert provider.events[:3] == ["connect", "reference", "subscribe"]
    quote = state.get_quote("HPG")
    assert quote is not None and quote.reference_price == 22_100.0
    assert any(message["symbol"] == "HPG" and "Ref" in message["patch"] for message in patches)
    assert managed._reference_refresh_session == reference_session_date().isoformat()
    await managed.shutdown()


@pytest.mark.asyncio
async def test_startup_partial_reference_does_not_mark_session_complete():
    _, universe = await _resolved_default()
    provider = MockMarketDataProvider(max_symbols=33)
    session_day = reference_session_date()
    provider.get_session_reference_data = AsyncMock(return_value={
        "HPG": {"session_date": session_day.isoformat(), "reference_price": 22_100.0}
    })
    managed = SubscriptionManager(
        provider=provider, state=MarketState(), store=NullMarketStateStore(), max_symbols=33,
    )
    managed.configure_server_universe(universe)

    assert await managed.initialize() is True
    assert managed._reference_refresh_session is None
    assert managed._reference_retry_at > 0
    await managed.shutdown()


@pytest.mark.asyncio
async def test_first_tick_schedules_only_one_reference_refresh_per_session():
    provider = MockMarketDataProvider(max_symbols=33)
    session_day = reference_session_date()
    provider.get_session_reference_data = AsyncMock(
        return_value={
            "HPG": {
                "session_date": session_day.isoformat(),
                "reference_price": 22_100.0,
                "ceiling_price": 23_600.0,
                "floor_price": 20_600.0,
            }
        }
    )
    managed = SubscriptionManager(
        provider=provider,
        state=MarketState(),
        store=NullMarketStateStore(),
        max_symbols=33,
    )
    managed._server_universe_symbols = {"HPG"}

    event = {
        "Ticker": "HPG",
        "Close": 22_200.0,
        "TradingDate": f"{session_day.isoformat()}T09:01:00+07:00",
    }
    managed._on_provider_event("trade", event, "HPG")
    managed._on_provider_event("trade", event, "HPG")
    assert managed._reference_refresh_task is not None
    await managed._reference_refresh_task

    provider.get_session_reference_data.assert_awaited_once()
    assert managed.state.get_quote("HPG").reference_session_date == session_day.isoformat()


@pytest.mark.asyncio
@pytest.mark.parametrize("initial_result", ["missing_symbol", "missing_band", "provider_failure"])
async def test_incomplete_reference_refresh_retries_after_cooldown(initial_result):
    provider = MockMarketDataProvider(max_symbols=33)
    session_day = reference_session_date()
    complete = {
        symbol: {
            "session_date": session_day.isoformat(),
            "reference_price": 22_100.0,
            "ceiling_price": 23_600.0,
            "floor_price": 20_600.0,
        }
        for symbol in ("HPG", "FPT")
    }
    first_result = {"HPG": complete["HPG"]}
    if initial_result == "missing_band":
        first_result = {**complete, "FPT": {**complete["FPT"], "floor_price": None}}
    elif initial_result == "provider_failure":
        first_result = RuntimeError("temporary reference endpoint failure")
    provider.get_session_reference_data = AsyncMock(side_effect=[first_result, complete])
    managed = SubscriptionManager(
        provider=provider,
        state=MarketState(),
        store=NullMarketStateStore(),
        max_symbols=33,
    )
    managed._server_universe_symbols = {"HPG", "FPT"}
    event = {
        "Ticker": "HPG", "Close": 22_200.0,
        "TradingDate": f"{session_day.isoformat()}T09:01:00+07:00",
    }

    managed._on_provider_event("trade", event, "HPG")
    await managed._reference_refresh_task
    assert managed._reference_refresh_session is None

    managed._on_provider_event("trade", event, "HPG")
    assert provider.get_session_reference_data.await_count == 1

    managed._reference_retry_at = 0.0
    managed._on_provider_event("trade", event, "HPG")
    await managed._reference_refresh_task
    assert provider.get_session_reference_data.await_count == 2
    assert managed._reference_refresh_session == session_day.isoformat()


@pytest.mark.asyncio
async def test_manager_does_not_truncate_universe_when_provider_capacity_is_too_small():
    _, universe = await _resolved_default()
    provider = MockMarketDataProvider(max_symbols=29)
    managed = SubscriptionManager(
        provider=provider,
        state=MarketState(),
        store=NullMarketStateStore(),
        max_symbols=29,
    )

    configured, _ = managed.configure_server_universe(universe)
    assert configured is False
    assert managed.get_server_universe_symbols() == []
    assert managed.get_universe_health()["status"] == "DEGRADED"
    assert managed.get_universe_health()["configured_size"] == 30
    assert managed.get_universe_health()["server_universe_size"] == 0


def test_two_websocket_clients_keep_isolated_interests_and_never_mutate_upstream():
    universe = {"HPG", "FPT"}
    market_state._quotes.pop("HPG", None)
    market_state._quotes.pop("FPT", None)
    desired_before = set(subscription_manager._desired_symbols)

    with patch.object(subscription_manager, "_server_universe_symbols", universe), \
         patch.object(subscription_manager, "_desired_symbols", set(universe)), \
         patch.object(subscription_manager.provider, "set_subscriptions", new_callable=AsyncMock) as upstream:
        with client.websocket_connect("/ws/market") as first, client.websocket_connect("/ws/market") as second:
            first_status = json.loads(first.receive_text())
            assert first_status["type"] == "status"
            assert set(first_status["realtime_universe_symbols"]) == universe
            assert json.loads(second.receive_text())["type"] == "status"

            first.send_text(json.dumps({"type": "subscribe", "symbols": ["HPG"]}))
            second.send_text(json.dumps({"type": "subscribe", "symbols": ["FPT"]}))
            first_ack = json.loads(first.receive_text())
            second_ack = json.loads(second.receive_text())
            assert first_ack["subscribed_symbols"] == ["HPG"]
            assert second_ack["subscribed_symbols"] == ["FPT"]

            first.send_text(json.dumps({"type": "unsubscribe", "symbols": ["HPG"]}))
            assert json.loads(first.receive_text())["subscribed_symbols"] == []
            second.send_text(
                json.dumps({"type": "subscribe", "symbols": [], "replace": False})
            )
            assert json.loads(second.receive_text())["subscribed_symbols"] == ["FPT"]
            upstream.assert_not_awaited()
            assert set(subscription_manager._desired_symbols) == universe

    # Patch restoration and connection cleanup are both deterministic.
    assert set(subscription_manager._desired_symbols) == desired_before
    assert manager.active_count == 0


def test_outside_universe_is_acknowledged_and_never_hydrated():
    with patch.object(subscription_manager, "_server_universe_symbols", {"HPG"}), \
         patch.object(subscription_manager, "hydrate_missing_market_state", new_callable=AsyncMock) as hydrate:
        with client.websocket_connect("/ws/market") as ws:
            ws.receive_text()
            ws.send_text(
                json.dumps(
                    {
                        "type": "subscribe",
                        "symbols": ["VNINDEX", 7, "bad symbol"],
                    }
                )
            )
            ack = json.loads(ws.receive_text())

    assert ack["type"] == "subscription_ack"
    assert ack["accepted_symbols"] == []
    assert ack["unavailable_symbols"] == ["VNINDEX"]
    assert ack["outside_symbols"] == ["VNINDEX"]
    assert ack["invalid_symbols"] == ["item[1]", "BAD SYMBOL"]
    assert ack["rejected_symbols"] == ["item[1]", "BAD SYMBOL"]
    hydrate.assert_not_awaited()


@pytest.mark.asyncio
async def test_quote_and_analytics_fanout_is_filtered_per_client():
    first = MagicMock()
    second = MagicMock()
    first.scope = {}
    second.scope = {}
    first.send_text = AsyncMock()
    second.send_text = AsyncMock()
    manager._active_connections.update({first, second})
    manager._client_subscriptions[first] = {"HPG", "CHPG2617"}
    manager._client_subscriptions[second] = {"FPT"}
    try:
        manager.broadcast_patch_threadsafe(
            {"type": "patch", "symbol": "HPG", "patch": {"Traded": 22.1}}
        )
        manager.broadcast_analytics_patch("CHPG2617", {"iv_trade": 0.31})
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        sent_first = [json.loads(call.args[0]) for call in first.send_text.await_args_list]
        assert [message["type"] for message in sent_first] == ["patch", "analytics_patch"]
        second.send_text.assert_not_awaited()

        manager._client_subscriptions[second].add("HPG")
        manager.broadcast_patch_threadsafe(
            {"type": "patch", "symbol": "HPG", "patch": {"Traded": 22.2}}
        )
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert second.send_text.await_count == 1
    finally:
        manager.disconnect(first)
        manager.disconnect(second)
