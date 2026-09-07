"""Retrieval: the trigger (step 1) and the ranking (step 2).

Before this, `get_news` ran only when the question contained a word from a fixed list, and
the store then returned the newest rows for the ticker. So a qualitative question phrased
outside that vocabulary reached the model with ZERO disclosures - not badly ranked ones,
none - and the model correctly reported no coverage. That is a trigger bug, not a ranking
bug, and it had to be fixed first.
"""
import pytest

from app.ai.tools.tool_executor import ToolExecutor
from app.ai.ai_schemas import ResearchContextEnvelope, SelectedInstrumentContext
from app.instruments.instrument_registry import instrument_registry

pytestmark = pytest.mark.asyncio


def _ctx(symbol="HPG", kind="STOCK", page="dashboard"):
    return ResearchContextEnvelope(
        activePage=page,
        selectedInstrument=SelectedInstrumentContext(symbol=symbol, instrumentType=kind),
    )


async def _run(query, ctx=None, budget=4):
    await instrument_registry.initialize()
    ex = ToolExecutor(max_tool_calls=budget)
    executed = await ex.resolve_and_execute_proactive_tools(query, ctx or _ctx())
    return executed, {e["tool"] for e in executed}


# ------------------------------------------------------------------- step 1
async def test_a_qualitative_question_outside_the_keyword_list_still_gets_disclosures():
    """The motivating case. 'pha loang' (dilution) is in no keyword list, and used to
    produce a reply grounded on nothing."""
    _, tools = await _run("HPG co rui ro pha loang khong?")
    assert "get_news" in tools


async def test_the_users_own_words_become_the_ranking_query():
    executed, _ = await _run("HPG co rui ro pha loang khong?")
    news = next(e for e in executed if e["tool"] == "get_news")
    assert news["args"]["symbol"] == "HPG"
    assert "pha loang" in news["args"]["query"]


async def test_an_explicit_news_word_still_routes_as_before():
    executed, tools = await _run("what has VPB announced lately?", _ctx("VPB"))
    assert "get_news" in tools
    news = next(e for e in executed if e["tool"] == "get_news")
    assert news["args"]["symbol"] == "VPB"


async def test_a_purely_quantitative_question_stays_lean():
    """Enrichment must not bury the number that was actually asked for."""
    _, tools = await _run("is HPG up or down today?")
    assert "get_news" not in tools
    assert "get_corporate_actions" not in tools


async def test_a_price_question_in_vietnamese_also_stays_lean():
    _, tools = await _run("giá HPG bao nhiêu?")
    assert "get_news" not in tools


async def test_essential_reads_keep_their_slot_ahead_of_enrichment():
    """A bounded executor starves whatever runs last. Closing prices outrank headlines:
    with the market shut, history must survive even on the tightest budget."""
    closed = ResearchContextEnvelope(
        activePage="dashboard",
        selectedInstrument=SelectedInstrumentContext(symbol="CVPB2615", instrumentType="CW"),
        marketSessionActive=False,
    )
    executed, tools = await _run("tell me about CVPB2615", closed, budget=4)
    assert {"get_quote", "get_instrument", "get_quant"} <= tools
    assert "get_history" in tools, "history lost its slot to enrichment"
    assert len(executed) <= 4


async def test_enrichment_uses_leftover_budget_when_there_is_room():
    executed, tools = await _run("what should I know about HPG?", _ctx(), budget=6)
    assert "get_quote" in tools
    assert "get_news" in tools
    assert len(executed) <= 6


# ------------------------------------------------------------------- step 2
async def test_news_tool_reports_how_its_rows_were_chosen():
    """The model must be able to tell targeted evidence from a recency dump."""
    from app.ai.tools.research_tools import get_news

    result = await get_news(symbol="HPG", query="pha loang")
    assert result.get("provenance") == "RESEARCH_ENRICHMENT"
    if result.get("status") != "UNAVAILABLE":
        assert result["ranked_by"] in ("RELEVANCE_AND_RECENCY", "RECENCY")


async def test_ranked_by_is_recency_when_no_query_is_supplied():
    from app.ai.tools.research_tools import get_news

    result = await get_news(symbol="HPG")
    if result.get("status") != "UNAVAILABLE":
        assert result["ranked_by"] == "RECENCY"
        assert result["matched_query"] is None
