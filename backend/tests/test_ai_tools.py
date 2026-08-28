import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient

from app.main import app
from app.market_data.market_state import market_state
from app.market_data.market_schemas import CanonicalQuote
from app.instruments.instrument_registry import instrument_registry
from app.instruments.instrument_schemas import (
    CoveredWarrantSpecification,
    InstrumentLifecycleStatus,
    DataQualityStatus,
    MetadataVerificationStatus,
)
from app.quant.quant_engine import live_quant_engine
from app.ai.tools.market_tools import (
    get_market_status,
    get_quote,
    get_order_book,
    get_dashboard_snapshot,
)
from app.ai.tools.instrument_tools import get_instrument
from app.ai.tools.quant_tools import get_quant
from app.ai.tools.tool_executor import ToolExecutor, extract_symbols_from_query
from app.ai.ai_schemas import ResearchContextEnvelope, SelectedInstrumentContext, ChatRequest
from app.ai.openrouter_client import OpenRouterClient
from app.ai.ai_router import get_client

client = TestClient(app)


class MockHttpxResponse:
    def __init__(self, status_code: int, json_data: dict | None = None):
        self.status_code = status_code
        self._json_data = json_data or {}

    def json(self):
        return self._json_data

    def raise_for_status(self):
        pass


@pytest.fixture(autouse=True)
def setup_market_and_instrument_state():
    # Hydrate canonical HPG quote into MarketState
    hpg_quote = CanonicalQuote(
        symbol="HPG",
        instrument_type="STOCK",
        last_price=22000.0,
        reference_price=21800.0,
        open_price=21850.0,
        high_price=22100.0,
        low_price=21800.0,
        price_change=200.0,
        price_change_percent=0.009174,
        total_volume=8143000,
        bid1_price=21950.0,
        bid1_quantity=285500,
        ask1_price=22000.0,
        ask1_quantity=741600,
        bid2_price=21900.0,
        bid2_quantity=454200,
        ask2_price=22050.0,
        ask2_quantity=326100,
        bid3_price=21850.0,
        bid3_quantity=442000,
        ask3_price=22100.0,
        ask3_quantity=411100,
        source_timestamp=1700000000,
    )
    market_state.restore_quote(hpg_quote)

    # Hydrate CHPG2541 with missing terms
    chpg_quote = CanonicalQuote(
        symbol="CHPG2541",
        instrument_type="CW",
        last_price=None,
        reference_price=300.0,
        bid1_price=290.0,
        bid1_quantity=100,
        ask1_price=300.0,
        ask1_quantity=100,
        underlying_symbol="HPG",
        source_timestamp=1700000000,
    )
    market_state.restore_quote(chpg_quote)


def test_1_and_2_get_quote_matches_canonical_market_state_values():
    """1 & 2. Copilot can access HPG MarketState data and values match canonical state."""
    quote_data = get_quote("HPG")

    assert quote_data["symbol"] == "HPG"
    assert quote_data["instrument_type"] == "STOCK"
    assert quote_data["last_price"] == 22000.0
    assert quote_data["reference_price"] == 21800.0
    assert quote_data["bid1_price"] == 21950.0
    assert quote_data["ask1_price"] == 22000.0
    assert quote_data["spread"] == 50.0
    assert quote_data["total_volume"] == 8143000
    assert quote_data["data_source"] == "FIINQUANT_REALTIME"
    assert quote_data["provenance"] == "FIINQUANT_REALTIME"


def test_3_get_dashboard_snapshot_reads_memory_without_new_subscriptions():
    """3. Dashboard snapshot reads current universe from memory without triggering new provider requests."""
    snapshot = get_dashboard_snapshot(["HPG", "NVL", "VHM", "CVHM2615", "CHPG2541"])

    assert snapshot["universe_size"] == 5
    assert snapshot["provenance"] == "MARKET_STATE"

    hpg = next(item for item in snapshot["instruments"] if item["symbol"] == "HPG")
    assert hpg["last_price"] == 22000.0
    assert hpg["bid1_price"] == 21950.0


@pytest.mark.asyncio
async def test_4_get_instrument_does_not_fabricate_missing_metadata():
    """4. get_instrument returns null for missing metadata without fabricating ratio=1 or strike=0."""
    spec = await get_instrument("CHPG2541")

    assert spec["symbol"] == "CHPG2541"
    # Unverified or partial metadata must remain None
    assert spec["strike_price"] is None
    assert spec["exercise_ratio"] is None
    assert spec["maturity_date"] is None


@pytest.mark.asyncio
async def test_5_and_6_get_quant_delegates_and_returns_structured_missing_inputs():
    """5 & 6. get_quant delegates to QuantEngine and returns structured diagnostics when inputs missing."""
    quant = await get_quant("CHPG2541")

    assert quant["symbol"] == "CHPG2541"
    assert quant["instrument_type"] == "CW"
    assert quant["is_available"] is False
    assert quant["status"] == "INCOMPLETE_INPUTS"
    assert "missing_inputs" in quant
    assert isinstance(quant["missing_inputs"], list)
    assert quant["provenance"] == "PROJECT_QUANT_ENGINE"


@pytest.mark.asyncio
async def test_7_ui_context_resolves_referenced_symbol():
    """7. UI context envelope resolves 'this stock' or 'this warrant' to correct symbol tool calls."""
    executor = ToolExecutor(max_tool_calls=4)
    envelope = ResearchContextEnvelope(
        activePage="dashboard",
        selectedInstrument=SelectedInstrumentContext(
            symbol="HPG",
            instrumentType="STOCK",
        ),
    )

    executed = await executor.resolve_and_execute_proactive_tools("is this stock going up or down?", envelope)
    assert len(executed) >= 1
    assert executed[0]["tool"] == "get_quote"
    assert executed[0]["args"]["symbol"] == "HPG"
    assert executed[0]["result"]["last_price"] == 22000.0


@pytest.mark.asyncio
async def test_8_bounded_tool_execution_limits():
    """8. Bounded tool loop prevents unbounded calls or loops (max 4)."""
    executor = ToolExecutor(max_tool_calls=2)

    await executor.call_tool("get_quote", {"symbol": "HPG"})
    await executor.call_tool("get_quote", {"symbol": "NVL"})
    overflow = await executor.call_tool("get_quote", {"symbol": "VHM"})

    assert len(executor.executed_calls) == 2
    assert "error" in overflow
    assert overflow["provenance"] == "EXECUTION_BOUND_GUARD"


@pytest.mark.asyncio
async def test_9_read_only_security_blocks_unauthorized_tools():
    """9. Security check: whitelisted execution blocks unauthorized tool names."""
    executor = ToolExecutor(max_tool_calls=4)
    blocked = await executor.call_tool("place_order", {"symbol": "HPG", "qty": 100})

    assert "error" in blocked
    assert blocked["provenance"] == "SECURITY_GUARD"


def test_10_get_market_status_includes_provenance():
    """10. get_market_status exposes clean session status with APP_MARKET_SESSION provenance."""
    status = get_market_status()

    assert "market_session" in status
    assert "market_session_active" in status
    assert "quote_display_eligible" in status
    assert status["provenance"] == "APP_MARKET_SESSION"
    # Never leaks passwords or raw auth secrets
    assert "password" not in str(status).lower()
    assert "token" not in str(status).lower()


@pytest.mark.asyncio
async def test_11_chat_endpoint_supplies_canonical_data_for_hpg():
    """11. Chat endpoint runs tool layer and feeds canonical HPG state to OpenRouter system prompt."""
    fake_client = OpenRouterClient(api_key="test-key", model="stealth/ox-alpha")
    app.dependency_overrides[get_client] = lambda: fake_client

    captured_system_prompt = None

    async def fake_stream_chat(messages, system_prompt=None):
        nonlocal captured_system_prompt
        captured_system_prompt = system_prompt
        yield "HPG is currently trading at 22,000 VND, up 0.92% today."

    with patch.object(fake_client, "stream_chat", side_effect=fake_stream_chat):
        response = client.post(
            "/api/ai/chat",
            json={
                "messages": [{"role": "user", "content": "is HPG up or down in price?"}],
                "stream": True,
            },
        )

        app.dependency_overrides.clear()
        assert response.status_code == 200
        assert captured_system_prompt is not None
        # Verify canonical market data block was injected with HPG quote
        assert "<canonical_market_data>" in captured_system_prompt
        assert "HPG" in captured_system_prompt
        assert "22000.0" in captured_system_prompt or "22000" in captured_system_prompt
