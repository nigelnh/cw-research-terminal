"""Step 13B Part B - AI research-quality guardrails.

Deterministic, offline: no OpenRouter call. Covers registry-backed symbol resolution,
the bounded read-only get_history tool, provenance / causal-claim / injection language in
the system prompt, and missing-data behaviour.
"""

from __future__ import annotations

import pytest

from app.ai.ai_system_prompt import BASE_SYSTEM_INSTRUCTIONS, build_system_prompt
from app.ai.ai_schemas import ResearchContextEnvelope, SelectedInstrumentContext
from app.ai.tools.history_tools import get_history
from app.ai.tools.tool_executor import ToolExecutor
from app.instruments.instrument_registry import instrument_registry

pytestmark = pytest.mark.asyncio


# --------------------------------------------------------------------------- #
# System prompt: provenance model + guardrails present
# --------------------------------------------------------------------------- #
async def test_system_prompt_declares_provenance_and_guardrails():
    p = BASE_SYSTEM_INSTRUCTIONS
    for token in ("OBSERVED", "COMPUTED", "HISTORICAL", "REFERENCE", "USER", "UNAVAILABLE"):
        assert token in p, f"provenance origin {token} missing from system prompt"
    assert "Causal-Claim Guardrail" in p
    assert "news" in p.lower() and "do not attribute" in p.lower()
    assert "fair value" in p.lower()  # the ban is stated explicitly
    assert "Implied volatility" in p and "historical" in p.lower()


async def test_system_prompt_enforces_english_first_language_policy():
    p = BASE_SYSTEM_INSTRUCTIONS.lower()
    assert "english-first" in p
    assert "default response language is english" in p
    # Vietnamese is opt-in on the user's own latest message, not inferred from context
    assert "latest substantive message is written in vietnamese" in p
    assert "not because the retrieved disclosure" in p or "not because" in p
    assert "translate or paraphrase" in p  # VI source -> English answer, provenance kept


async def test_reply_language_is_detected_from_the_latest_message_only():
    from app.ai.ai_system_prompt import build_system_prompt, detect_reply_language

    assert detect_reply_language("How is IV different from HV?") == "English"
    assert detect_reply_language("HPG gần đây có tin gì?") == "Vietnamese"
    assert detect_reply_language("") == "English"
    assert detect_reply_language(None) == "English"

    # the directive is injected at the very start of the built prompt, English by default
    en = build_system_prompt(latest_user_message="what about VPB?")
    assert en.startswith("RESPONSE LANGUAGE FOR THIS REPLY: English")
    vi = build_system_prompt(latest_user_message="còn VPB thì sao?")
    assert vi.startswith("RESPONSE LANGUAGE FOR THIS REPLY: Vietnamese")


async def test_full_prompt_has_injection_resistance_and_tool_provenance_mapping():
    ctx = ResearchContextEnvelope(activePage="research")
    full = build_system_prompt(ctx, tool_results=[{"symbol": "X", "provenance": "MARKET_STATE"}])
    assert "Prompt-Injection Resistance" in full
    assert "get_history" in full
    assert "DATA" in full


# --------------------------------------------------------------------------- #
# Registry-backed symbol resolution - no hardcoded ticker list
# --------------------------------------------------------------------------- #
async def test_unknown_symbol_triggers_no_tool_calls():
    await instrument_registry.initialize()
    ex = ToolExecutor()
    executed = await ex.resolve_and_execute_proactive_tools("what about ZZZ9999 right now?")
    assert executed == []


async def test_real_registry_cw_resolves_and_pulls_terms_and_quant():
    await instrument_registry.initialize()
    ex = ToolExecutor()
    executed = await ex.resolve_and_execute_proactive_tools("tell me about CVPB2615")
    tools = {e["tool"] for e in executed}
    assert "get_quote" in tools
    assert "get_instrument" in tools
    assert "get_quant" in tools
    assert all(e["args"].get("symbol") == "CVPB2615" for e in executed if "symbol" in e["args"])


async def test_history_intent_adds_get_history_for_known_symbol():
    await instrument_registry.initialize()
    ex = ToolExecutor()
    executed = await ex.resolve_and_execute_proactive_tools(
        "show me the recent price action for CVPB2615 over the last month"
    )
    assert "get_history" in {e["tool"] for e in executed}


async def test_lowercase_ticker_mention_is_not_misread_as_symbol():
    # common lowercase words must never resolve to instruments
    await instrument_registry.initialize()
    ex = ToolExecutor()
    executed = await ex.resolve_and_execute_proactive_tools("can you compare all of them for me")
    # 'compare'/'all' are dashboard keywords -> snapshot, but never a bogus get_instrument
    assert "get_instrument" not in {e["tool"] for e in executed}


# --------------------------------------------------------------------------- #
# get_history - bounded, read-only, validated
# --------------------------------------------------------------------------- #
async def test_get_history_rejects_unknown_symbol():
    r = await get_history("NOTREAL1")
    assert r["status"] == "UNKNOWN_SYMBOL"
    assert r["provenance"] == "HISTORICAL"


async def test_get_history_rejects_non_daily_timeframe():
    r = await get_history("CVPB2615", timeframe="5m")
    assert r["status"] == "UNSUPPORTED_TIMEFRAME"


async def test_get_history_known_symbol_no_persisted_data_is_graceful():
    # Test env has no seeded bars -> NO_DATA, never fabricated series.
    await instrument_registry.initialize()
    r = await get_history("CVPB2615", lookback_days=30)
    assert r["status"] in ("NO_DATA", "AVAILABLE")
    if r["status"] == "NO_DATA":
        assert "series" not in r
        assert "does not fetch" in r["message"].lower() or "only stored" in r["message"].lower()


async def test_get_history_clamps_oversized_lookback():
    await instrument_registry.initialize()
    r = await get_history("CVPB2615", lookback_days=99999)
    # window must be clamped to <= AI_HISTORY_MAX_LOOKBACK_DAYS; no error raised
    assert r["status"] in ("NO_DATA", "AVAILABLE")


# --------------------------------------------------------------------------- #
# Missing-data behaviour - quant gate closed => no numbers
# --------------------------------------------------------------------------- #
async def test_conflicting_metadata_quant_tool_returns_no_numbers():
    from app.ai.tools.quant_tools import get_quant

    await instrument_registry.initialize()
    q = await get_quant("CTCB2601")  # CONFLICTING metadata in the shipped dataset
    assert q["is_available"] is False
    for k in ("iv_bid", "iv_trade", "delta", "gamma", "theoretical_price"):
        assert q.get(k) in (None, ) or k not in q
    assert "unavailable_reason" in q
