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
    get_market_context,
    get_market_status,
    get_quote,
    get_order_book,
    get_dashboard_snapshot,
)
from app.ai.tools.instrument_tools import get_instrument
from app.ai.tools.quant_tools import get_quant
from app.ai.tools.tool_executor import ToolExecutor
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
def setup_market_and_instrument_state(monkeypatch):
    from app.market_data.trading_calendar import reference_session_date
    from app.market_data.market_session import market_session
    now = market_session.get_vn_now()
    session = reference_session_date(now).isoformat()
    timestamp = int(now.timestamp() * 1000)

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
        source_timestamp=timestamp, trade_timestamp=timestamp, book_timestamp=timestamp,
        received_timestamp=timestamp, reference_timestamp=timestamp,
        market_session_date=session, reference_session_date=session,
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
        source_timestamp=timestamp, trade_timestamp=timestamp, book_timestamp=timestamp,
        received_timestamp=timestamp, reference_timestamp=timestamp,
        market_session_date=session, reference_session_date=session,
    )
    market_state.restore_quote(chpg_quote)


@pytest.mark.asyncio
async def test_1_and_2_get_quote_matches_canonical_market_state_values():
    """1 & 2. Copilot can access HPG MarketState data and values match canonical state."""
    quote_data = await get_quote("HPG")

    assert quote_data["symbol"] == "HPG"
    assert quote_data["instrument_type"] == "STOCK"
    assert quote_data["last_price"] == 22000.0
    assert quote_data["reference_price"] == 21800.0
    assert quote_data["bid1_price"] == 21950.0
    assert quote_data["ask1_price"] == 22000.0
    assert quote_data["spread"] == 50.0
    assert quote_data["total_volume"] == 8143000
    assert quote_data["data_source"] == "LIVE_FEED"
    assert quote_data["provenance"]["quote"]["source"] == "LIVE_FEED"


@pytest.mark.asyncio
async def test_3_get_dashboard_snapshot_reads_memory_without_new_subscriptions():
    """3. Dashboard snapshot reads current universe from memory without triggering new provider requests."""
    snapshot = await get_dashboard_snapshot(["HPG", "NVL", "VHM", "CVHM2615", "CHPG2541"])

    assert snapshot["universe_size"] == 5
    assert snapshot["provenance"] == "RESOLVED_INSTRUMENT_VIEW"

    hpg = next(item for item in snapshot["instruments"] if item["symbol"] == "HPG")
    assert hpg["last_price"] == 22000.0
    assert hpg["bid1_price"] == 21950.0


@pytest.mark.asyncio
async def test_market_context_uses_the_same_session_scoped_overview_as_dashboard():
    payload = {
        "availability": "AVAILABLE",
        "indices": [{"symbol": "VNINDEX", "value": 1847.17}],
        "top_stock_volume": [{"symbol": "HPG", "volume": 5_000_000}],
        "top_cw_volume": [],
        "market_metrics": {
            "session_date": "2026-09-09",
            "liquidity": {"total_value": 1_000_000, "availability": "AVAILABLE"},
            "foreign_flow": {"net_volume": 12_000, "availability": "AVAILABLE"},
        },
        "market_phase": "CONTINUOUS_AM",
        "as_of": "2026-09-09T10:00:00+07:00",
    }
    with patch(
        "app.market_data.market_overview_service.market_overview_service.get",
        new=AsyncMock(return_value=payload),
    ):
        result = await get_market_context()

    assert result["provenance"] == "APP_MARKET_OVERVIEW"
    assert result["market_metrics"]["foreign_flow"]["net_volume"] == 12_000
    assert result["indices"][0]["symbol"] == "VNINDEX"


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
async def test_6b_get_quant_serves_last_completed_session_when_live_is_session_gated(monkeypatch):
    from datetime import datetime
    from app.market_data.trading_calendar import VN_TZ
    monkeypatch.setattr("app.quant.quant_engine.get_vietnam_now", lambda: datetime(2026, 9, 6, 8, tzinfo=VN_TZ))
    """Outside trading hours the live path returns MARKET_INPUT_SESSION_MISMATCH. get_quant
    must then fall back to the last completed session's EOD analytics - the SAME numbers
    the watchlist IV columns and the instrument panel already show - not report IV as
    unavailable."""
    from datetime import date
    from app.quant.quant_schemas import (
        WarrantAnalytics,
        WarrantGreeks,
        MoneynessCategory,
        GreeksVolatilitySource,
    )

    live_gated = WarrantAnalytics(
        symbol="CHPG2617", underlying_symbol="HPG",
        calculated_at="2026-09-06T08:00:00+07:00",
        is_available=False, unavailable_reason="MARKET_INPUT_SESSION_MISMATCH",
    )
    eod_ok = WarrantAnalytics(
        symbol="CHPG2617", underlying_symbol="HPG",
        calculated_at="2026-09-04T15:00:00+07:00", session_date="2026-09-04", is_available=True,
        moneyness=0.85433, moneyness_category=MoneynessCategory.OTM,
        iv_bid=0.41216, iv_trade=0.431195, iv_ask=0.431195, iv_mid=0.421697,
        historical_volatility=0.2494, theoretical_price=157.26,
        greeks=WarrantGreeks(
            delta=0.10159, gamma=0.0000138, theta=-1.9, vega=15.81, rho=10.01,
            volatility_source=GreeksVolatilitySource.IV_TRADE,
        ),
    )

    with patch.object(
        live_quant_engine, "compute_warrant_analytics",
        new=AsyncMock(return_value=live_gated),
    ), patch.object(
        live_quant_engine, "compute_eod_analytics",
        new=AsyncMock(return_value=eod_ok),
    ) as eod_mock:
        quant = await get_quant("CHPG2617")

    assert quant["is_available"] is True
    assert quant["status"] == "AVAILABLE"
    assert quant["basis"] == "LAST_COMPLETED_SESSION"
    assert quant["as_of_session"]  # ISO date of the completed session
    assert quant["iv_trade"] == 0.431195
    assert quant["iv_bid"] == 0.41216
    assert quant["delta"] == 0.10159
    assert quant["historical_volatility"] == 0.2494
    called_sym, called_session = eod_mock.call_args.args
    assert called_sym == "CHPG2617"
    assert isinstance(called_session, date)


@pytest.mark.asyncio
async def test_6c_get_quant_reports_unavailable_only_when_both_live_and_eod_decline(monkeypatch):
    from datetime import datetime
    from app.market_data.trading_calendar import VN_TZ
    monkeypatch.setattr("app.quant.quant_engine.get_vietnam_now", lambda: datetime(2026, 9, 6, 8, tzinfo=VN_TZ))
    """If the last-session EOD compute also declines (e.g. unverified metadata), the tool
    surfaces that reason - not a fabricated number and not the raw session-mismatch."""
    from app.quant.quant_schemas import WarrantAnalytics

    live_gated = WarrantAnalytics(
        symbol="CHPG2617", underlying_symbol="HPG",
        calculated_at="2026-09-06T08:00:00+07:00",
        is_available=False, unavailable_reason="MARKET_INPUT_SESSION_MISMATCH",
    )
    eod_gated = WarrantAnalytics(
        symbol="CHPG2617", underlying_symbol="HPG",
        calculated_at="2026-09-04T15:00:00+07:00",
        is_available=False, unavailable_reason="METADATA_NOT_VERIFIED_CURRENT (PENDING)",
    )

    with patch.object(
        live_quant_engine, "compute_warrant_analytics",
        new=AsyncMock(return_value=live_gated),
    ), patch.object(
        live_quant_engine, "compute_eod_analytics",
        new=AsyncMock(return_value=eod_gated),
    ):
        quant = await get_quant("CHPG2617")

    assert quant["is_available"] is False
    assert quant["status"] == "INCOMPLETE_INPUTS"
    assert "METADATA_NOT_VERIFIED_CURRENT" in quant["unavailable_reason"]


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


# --------------------------------------------------------------------------- #
# Step 14A: research-enrichment tool routing (get_news / get_corporate_actions)
# --------------------------------------------------------------------------- #
from app.ai.ai_system_prompt import build_system_prompt  # noqa: E402
from app.ai.tools import research_tools  # noqa: E402


@pytest.mark.asyncio
async def test_12_corporate_action_query_routes_get_corporate_actions():
    """A dividend / corporate-action question about a resolved symbol pulls get_corporate_actions."""
    executor = ToolExecutor(max_tool_calls=4)
    envelope = ResearchContextEnvelope(
        activePage="dashboard",
        selectedInstrument=SelectedInstrumentContext(symbol="HPG", instrumentType="STOCK"),
    )
    executed = await executor.resolve_and_execute_proactive_tools(
        "has HPG paid any dividends recently, and when is the record date?", envelope
    )
    tools = {e["tool"] for e in executed}
    assert "get_corporate_actions" in tools
    ca = next(e for e in executed if e["tool"] == "get_corporate_actions")
    assert ca["args"]["symbol"] == "HPG"
    assert ca["result"]["provenance"] == "RESEARCH_ENRICHMENT"


@pytest.mark.asyncio
async def test_13_news_query_without_symbol_routes_get_news():
    """A general disclosure question (no symbol) on the NEWS page pulls get_news with no symbol."""
    executor = ToolExecutor(max_tool_calls=4)
    envelope = ResearchContextEnvelope(activePage="news")
    executed = await executor.resolve_and_execute_proactive_tools(
        "any notable exchange disclosures today?", envelope
    )
    tools = {e["tool"] for e in executed}
    assert tools == {"get_news"}
    assert "symbol" not in executed[0]["args"] or not executed[0]["args"].get("symbol")
    assert executed[0]["result"]["provenance"] == "RESEARCH_ENRICHMENT"


@pytest.mark.asyncio
async def test_14_symbol_news_query_routes_get_news_for_that_symbol():
    executor = ToolExecutor(max_tool_calls=4)
    envelope = ResearchContextEnvelope(
        activePage="research",
        selectedInstrument=SelectedInstrumentContext(symbol="VPB", instrumentType="STOCK"),
    )
    executed = await executor.resolve_and_execute_proactive_tools(
        "what has VPB announced lately?", envelope
    )
    news = next((e for e in executed if e["tool"] == "get_news"), None)
    assert news is not None and news["args"]["symbol"] == "VPB"


@pytest.mark.asyncio
async def test_15_plain_price_query_does_not_pull_research_tools():
    """No false positives: a pure price question must not trigger news / corporate actions."""
    executor = ToolExecutor(max_tool_calls=4)
    envelope = ResearchContextEnvelope(
        activePage="dashboard",
        selectedInstrument=SelectedInstrumentContext(symbol="HPG", instrumentType="STOCK"),
    )
    executed = await executor.resolve_and_execute_proactive_tools("is HPG up or down today?", envelope)
    tools = {e["tool"] for e in executed}
    assert "get_news" not in tools
    assert "get_corporate_actions" not in tools


@pytest.mark.asyncio
async def test_16_research_tools_unavailable_without_db_but_well_formed():
    n = await research_tools.get_news(symbol="HPG")
    assert n["status"] == "UNAVAILABLE"
    assert n["provenance"] == "RESEARCH_ENRICHMENT"
    bad = await research_tools.get_corporate_actions("")
    assert bad["status"] == "INVALID_ARGUMENT"


def test_17_system_prompt_documents_research_provenance_and_causal_restraint():
    prompt = build_system_prompt(
        context=None,
        tool_results=[{
            "symbol": "HPG",
            "count": 1,
            "items": [{"title": "HPG: board resolution", "published_at": "2026-08-20", "source": "HSX"}],
            "causal_note": "These items were disclosed/effective near the stated dates. Do not assert they caused any price movement",
            "provenance": "RESEARCH_ENRICHMENT",
        }],
    )
    assert "RESEARCH_ENRICHMENT" in prompt
    assert "get_news" in prompt and "get_corporate_actions" in prompt
    assert "caused" in prompt.lower()
    assert "SCHEDULED" in prompt  # scheduled-vs-confirmed distinction is spelled out


@pytest.mark.asyncio
async def test_18_ranking_query_naming_a_ticker_also_pulls_the_dashboard_snapshot():
    """'most active HPG warrant by volume' names HPG but is asking to rank the CHPG set -
    without the multi-symbol snapshot the model gets one quote and nothing to rank, then
    tends to stall on 'let me query…'."""
    executor = ToolExecutor(max_tool_calls=4)
    envelope = ResearchContextEnvelope(
        activePage="dashboard", marketSessionActive=False, watchlist=["HPG", "CHPG2541"]
    )
    executed = await executor.resolve_and_execute_proactive_tools(
        "give me the most active HPG warrant by volume", envelope
    )
    tools = {e["tool"] for e in executed}
    assert "get_dashboard_snapshot" in tools
    assert "get_quote" in tools  # still fetched HPG's own quote
    snap = next(e for e in executed if e["tool"] == "get_dashboard_snapshot")
    assert snap["result"]["universe_size"] >= 1


@pytest.mark.asyncio
async def test_18b_which_cw_on_an_underlying_scopes_the_snapshot_to_that_underlyings_warrants():
    """'which cw is the most active in HPG?' - the snapshot should be narrowed to HPG's
    warrants (a short unambiguous list), not the whole watchlist."""
    await instrument_registry.initialize(current_date="2026-08-28")
    executor = ToolExecutor(max_tool_calls=4)
    envelope = ResearchContextEnvelope(
        activePage="dashboard", marketSessionActive=False,
        watchlist=["HPG", "FPT", "CHPG2541", "CFPT2628"],
    )
    executed = await executor.resolve_and_execute_proactive_tools(
        "which cw is the most active one in HPG?", envelope
    )
    snap = next(e for e in executed if e["tool"] == "get_dashboard_snapshot")
    assert snap["args"]["symbols"] == ["CHPG2541"]  # HPG's warrant from the watchlist only


@pytest.mark.asyncio
async def test_18c_dashboard_snapshot_rows_carry_underlying_symbol_for_cws():
    await instrument_registry.initialize(current_date="2026-08-28")
    snap = await get_dashboard_snapshot(["HPG", "CHPG2541"])
    cw = next(i for i in snap["instruments"] if i["symbol"] == "CHPG2541")
    assert cw["underlying_symbol"] == "HPG"
    stock = next(i for i in snap["instruments"] if i["symbol"] == "HPG")
    assert stock["underlying_symbol"] is None


@pytest.mark.asyncio
async def test_19_ranking_query_without_a_ticker_pulls_only_the_dashboard_snapshot():
    executor = ToolExecutor(max_tool_calls=4)
    envelope = ResearchContextEnvelope(activePage="dashboard", marketSessionActive=False)
    executed = await executor.resolve_and_execute_proactive_tools(
        "which warrant is most active right now?", envelope
    )
    assert {e["tool"] for e in executed} == {"get_dashboard_snapshot"}


@pytest.mark.asyncio
async def test_20_a_plain_single_symbol_volume_question_is_not_a_ranking_query():
    """No false positive: 'HPG's trading volume today' names one symbol and asks for one
    number - it must NOT pull the whole-universe snapshot."""
    executor = ToolExecutor(max_tool_calls=4)
    envelope = ResearchContextEnvelope(
        activePage="dashboard",
        selectedInstrument=SelectedInstrumentContext(symbol="HPG", instrumentType="STOCK"),
        marketSessionActive=True,
    )
    executed = await executor.resolve_and_execute_proactive_tools(
        "what is HPG's trading volume today?", envelope
    )
    assert "get_dashboard_snapshot" not in {e["tool"] for e in executed}


def test_21_system_prompt_forbids_promising_a_follow_up_query():
    prompt = build_system_prompt(
        context=None,
        tool_results=[{"symbol": "HPG", "status": "AVAILABLE", "provenance": "MARKET_STATE"}],
    )
    assert "COMPLETE and FINAL" in prompt
    assert "fire off queries" in prompt.lower()  # the exact stall phrasing this model uses
    assert "no way to run another tool" in prompt.lower()
    # ranking questions are explicitly routed to the dashboard snapshot
    assert "get_dashboard_snapshot" in prompt and "underlying_symbol" in prompt
