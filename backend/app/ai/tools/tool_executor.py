"""
Bounded Tool Execution Engine and Intent Resolver for Research Copilot.
Enforces execution bounds (max 4 tool calls per turn, request caching, read-only whitelist).
Proactively resolves live market context using canonical application services.

Symbol resolution is registry-backed: candidate tokens are extracted with a permissive
pattern and then validated against the canonical ``InstrumentResolver`` (InstrumentRegistry
+ curated HOSE equity / index allow-lists). There is no hardcoded ticker whitelist - a token
counts as a symbol only if the project actually recognises it.
"""

from typing import Dict, Any, List, Optional, Set
import re
import logging

from app.ai.ai_schemas import ResearchContextEnvelope
from app.ai.tools.tool_registry import execute_tool, TOOL_HANDLERS
from app.me.instrument_resolver import InstrumentResolver, ResolvedInstrument

logger = logging.getLogger(__name__)

# Permissive candidate patterns - the resolver is the authority on what is real.
#   CW:            C + 7 alphanumerics (HOSE covered-warrant convention)
#   equity/index:  2-8 char upper token, optionally digit-suffixed (VPB, HPG, VN30, VNINDEX)
_CW_CANDIDATE = re.compile(r"\bC[A-Z0-9]{7}\b", re.IGNORECASE)
_TICKER_CANDIDATE = re.compile(r"\b[A-Z]{2,}[0-9]{0,4}\b")

# "refers to the thing on screen" phrases (EN + VI)
_DEICTIC = (
    "this stock", "this warrant", "this instrument", "this cw", "this one",
    "mã này", "con này", "đang xem", "viewing", "current instrument", "selected",
)

DASHBOARD_KEYWORDS = {
    "dashboard", "bảng giá", "tổng quan", "overview", "portfolio",
    "best", "worst", "doing best", "up the most", "down the most",
    "tăng", "giảm", "cao nhất", "thấp nhất", "so sánh", "compare",
    "all", "tất cả", "danh mục", "watchlist",
}

MARKET_STATUS_KEYWORDS = {
    "market status", "market session", "phiên", "mở cửa", "đóng cửa",
    "nghỉ trưa", "lunch break", "trading hours", "is market open",
}

HISTORY_KEYWORDS = {
    "history", "historical", "recent price", "price action", "past week", "past month",
    "last week", "last month", "last few days", "trend", "drawdown", "over the last",
    "lịch sử", "diễn biến", "xu hướng", "vài ngày qua", "tuần qua", "tháng qua",
    "gần đây", "biến động giá",
}

ORDER_BOOK_KEYWORDS = (
    "order book", "sổ lệnh", "depth", "dư mua", "dư bán", "bid ask", "bid/ask", "khối lượng",
)

# Step 14A research enrichment: PostgreSQL-backed disclosure & corporate-action reads.
NEWS_KEYWORDS = {
    "news", "disclosure", "disclosures", "announcement", "announced", "headline", "filing",
    "press release", "tin tức", "tin bài", "công bố thông tin", "công bố", "thông báo",
    "bản tin",
}

CORP_ACTION_KEYWORDS = {
    "dividend", "dividends", "corporate action", "corporate actions", "record date",
    "ex-date", "ex date", "ex-dividend", "rights issue", "bonus issue", "bonus share",
    "stock dividend", "cash dividend", "agm", "egm", "shareholder meeting",
    "general meeting", "cổ tức", "chia cổ tức", "trả cổ tức", "quyền mua", "cổ phiếu thưởng",
    "ngày chốt quyền", "ngày giao dịch không hưởng quyền", "đại hội cổ đông", "đhđcđ",
    "họp cổ đông", "phát hành thêm",
}

# The broader SSI company-event stream: financial statements + insider / major-holder deals.
COMPANY_EVENT_KEYWORDS = {
    "financial statement", "financial statements", "financial report", "earnings report",
    "quarterly results", "quarterly earnings", "annual report", "q1", "q2", "q3", "q4",
    "insider", "insider transaction", "insider trading", "insider buying", "insider selling",
    "major shareholder", "major holder", "ownership change", "related party",
    "company events", "corporate events", "recent events", "what has happened",
    "báo cáo tài chính", "bctc", "kết quả kinh doanh", "lợi nhuận quý", "giao dịch nội bộ",
    "cổ đông lớn", "người nội bộ", "sự kiện doanh nghiệp",
}


def generate_activity_label(tool_name: str, args: Dict[str, Any]) -> str:
    """Generates clean, user-facing activity labels for tool execution."""
    sym = args.get("symbol", "")
    if tool_name == "get_quote":
        return f"Checking {sym} market data…" if sym else "Checking market quote…"
    elif tool_name == "get_order_book":
        return f"Checking {sym} order book…" if sym else "Checking order book…"
    elif tool_name == "get_quant":
        return f"Reviewing {sym} analytics…" if sym else "Calculating quantitative analytics…"
    elif tool_name == "get_instrument":
        return f"Retrieving {sym} contract terms…" if sym else "Retrieving instrument terms…"
    elif tool_name == "get_history":
        return f"Reading {sym} price history…" if sym else "Reading price history…"
    elif tool_name == "get_dashboard_snapshot":
        return "Checking your dashboard…"
    elif tool_name == "get_market_status":
        return "Checking market session status…"
    elif tool_name == "get_news":
        return f"Reading {sym} disclosures…" if sym else "Reading exchange disclosures…"
    elif tool_name == "get_corporate_actions":
        return f"Reading {sym} corporate actions…" if sym else "Reading corporate actions…"
    elif tool_name == "get_company_events":
        return f"Reading {sym} company events…" if sym else "Reading company events…"
    return "Analyzing market context…"


class ToolExecutor:
    """
    Manages bounded tool execution for a single Copilot conversation turn.
    Guarantees:
    - Maximum 4 tool calls per turn.
    - Caches identical tool results within the request turn.
    - Strict read-only whitelist.
    - Symbols are validated against the canonical registry before any tool runs.
    """

    def __init__(self, max_tool_calls: int = 4):
        self.max_tool_calls = max_tool_calls
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._executed_calls: List[Dict[str, Any]] = []
        self._activity_labels: List[str] = []
        self._resolver = InstrumentResolver()

    def _cache_key(self, tool_name: str, args: Dict[str, Any]) -> str:
        sym = args.get("symbol", "")
        symbols = args.get("symbols", [])
        extra = args.get("lookback_days", "")
        return f"{tool_name}:{sym}:{extra}:{','.join(sorted(symbols)) if isinstance(symbols, list) else ''}"

    async def call_tool(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Executes a single tool with caching and bounds enforcement."""
        if tool_name not in TOOL_HANDLERS:
            return {"error": f"Tool '{tool_name}' is not allowed.", "provenance": "SECURITY_GUARD"}

        key = self._cache_key(tool_name, args)
        if key in self._cache:
            return self._cache[key]

        if len(self._executed_calls) >= self.max_tool_calls:
            logger.warning(f"Tool call bound ({self.max_tool_calls}) reached. Skipping {tool_name}.")
            return {
                "error": "Execution limit reached for this turn.",
                "provenance": "EXECUTION_BOUND_GUARD",
            }

        label = generate_activity_label(tool_name, args)
        self._activity_labels.append(label)

        result = await execute_tool(tool_name, args)
        self._cache[key] = result
        self._executed_calls.append({
            "tool": tool_name,
            "args": args,
            "result": result,
            "activity_label": label,
        })
        return result

    async def _resolve_symbols(
        self, query: str, context: Optional[ResearchContextEnvelope]
    ) -> Dict[str, ResolvedInstrument]:
        """Extract candidate tokens, validate each against the canonical resolver, and
        fall back to the on-screen instrument for deictic phrases. Returns an ordered
        (dict-insertion) map of SYMBOL -> ResolvedInstrument, capped at 2 symbols."""
        candidates: List[str] = []
        for m in _CW_CANDIDATE.finditer(query):
            candidates.append(m.group(0).upper())
        for m in _TICKER_CANDIDATE.finditer(query):
            tok = m.group(0).upper()
            if tok not in candidates:
                candidates.append(tok)

        resolved: Dict[str, ResolvedInstrument] = {}
        for tok in candidates:
            if len(resolved) >= 2:
                break
            r = await self._resolver.resolve(tok)
            if r is not None:
                resolved[r.symbol] = r

        if not resolved and context:
            q_lower = query.lower()
            if any(k in q_lower for k in _DEICTIC):
                sym = None
                if context.selectedInstrument and context.selectedInstrument.symbol:
                    sym = context.selectedInstrument.symbol
                elif context.selectedSymbol:
                    sym = context.selectedSymbol
                if sym:
                    r = await self._resolver.resolve(sym)
                    if r is not None:
                        resolved[r.symbol] = r
        return resolved

    async def resolve_and_execute_proactive_tools(
        self,
        query: str,
        context: Optional[ResearchContextEnvelope] = None,
    ) -> List[Dict[str, Any]]:
        """
        Deterministically resolves user intent and proactively executes relevant tools.
        Ensures AI has canonical market state before synthesizing answers.
        """
        q_lower = query.lower()
        resolved = await self._resolve_symbols(query, context)

        wants_history = any(k in q_lower for k in HISTORY_KEYWORDS)
        wants_order_book = any(k in q_lower for k in ORDER_BOOK_KEYWORDS)
        is_dashboard_query = any(k in q_lower for k in DASHBOARD_KEYWORDS)
        wants_corp_actions = any(k in q_lower for k in CORP_ACTION_KEYWORDS)
        wants_company_events = any(k in q_lower for k in COMPANY_EVENT_KEYWORDS)
        wants_news = any(k in q_lower for k in NEWS_KEYWORDS)
        on_news_page = context is not None and context.activePage == "news"
        # Outside an active session there is no live quote to fetch - pull the last
        # completed session's end-of-day series so the model cites real closing values
        # instead of the "no quote available" dead end (Step 13C).
        market_closed = context is not None and context.marketSessionActive is False
        pull_eod = wants_history or market_closed

        # Case 1: one or more recognised symbols in the query / on screen
        if resolved:
            for sym, inst in resolved.items():
                await self.call_tool("get_quote", {"symbol": sym})

                if inst.instrument_type == "CW":
                    await self.call_tool("get_instrument", {"symbol": sym})
                    await self.call_tool("get_quant", {"symbol": sym})
                elif wants_order_book:
                    await self.call_tool("get_order_book", {"symbol": sym})

                # Step 14A/B: PostgreSQL-backed research reads — read-only, no upstream.
                # get_corporate_actions = dividends / ex-dates / meetings (price-adjustment
                # sense); get_company_events = the broader stream incl. financials + insider.
                if inst.instrument_type != "CW":
                    if wants_company_events:
                        await self.call_tool("get_company_events", {"symbol": sym})
                    if wants_corp_actions:
                        await self.call_tool("get_corporate_actions", {"symbol": sym})
                if wants_news:
                    await self.call_tool("get_news", {"symbol": sym})

                if pull_eod:
                    await self.call_tool("get_history", {"symbol": sym, "lookback_days": 30})

        # Case 2a: news / disclosure query with no specific symbol (or on the NEWS page)
        elif wants_news or (on_news_page and not is_dashboard_query):
            await self.call_tool("get_news", {})

        # Case 2: dashboard comparison query (e.g. "which stock is doing best?")
        elif is_dashboard_query:
            watched = context.watchedSymbols if (context and context.watchedSymbols) else None
            await self.call_tool("get_dashboard_snapshot", {"symbols": watched} if watched else {})

        # Case 3: market status query
        elif any(k in q_lower for k in MARKET_STATUS_KEYWORDS):
            await self.call_tool("get_market_status", {})

        return self._executed_calls

    @property
    def activity_labels(self) -> List[str]:
        return self._activity_labels

    @property
    def executed_calls(self) -> List[Dict[str, Any]]:
        return self._executed_calls
