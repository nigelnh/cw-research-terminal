"""
Bounded Tool Execution Engine and Intent Resolver for Research Copilot.
Enforces execution bounds (max 4 tool calls per turn, request caching, read-only whitelist).
Proactively resolves live market context using canonical application services.
"""

from typing import Dict, Any, List, Optional, Tuple, Set
import re
import logging

from app.ai.ai_schemas import ResearchContextEnvelope
from app.ai.tools.tool_registry import execute_tool, TOOL_HANDLERS

logger = logging.getLogger(__name__)

# Primary symbols recognized in the platform
PRIMARY_SYMBOLS = {"HPG", "NVL", "VHM", "CVHM2615", "CHPG2541"}
CW_PATTERN = re.compile(r"\b(C[A-Z0-9]{7})\b", re.IGNORECASE)
STOCK_PATTERN = re.compile(r"\b(HPG|NVL|VHM|FPT|VIC|MSN|MWG|SSI|VND|TCB|MBB|STB|VPB)\b", re.IGNORECASE)

# Dashboard/Comparative Intent Keywords
DASHBOARD_KEYWORDS = {
    "dashboard", "bảng giá", "tổng quan", "overview", "portfolio",
    "best", "worst", "doing best", "up the most", "down the most",
    "tăng", "giảm", "cao nhất", "thấp nhất", "so sánh", "compare",
    "all", "tất cả", "danh mục", "watchlist"
}

MARKET_STATUS_KEYWORDS = {
    "market status", "market session", "phiên", "mở cửa", "đóng cửa",
    "nghỉ trưa", "lunch break", "trading hours", "is market open"
}


def extract_symbols_from_query(query: str) -> Set[str]:
    """Extracts stock and CW ticker symbols mentioned in the user query."""
    symbols = set()
    for m in CW_PATTERN.finditer(query):
        symbols.add(m.group(1).upper())
    for m in STOCK_PATTERN.finditer(query):
        symbols.add(m.group(1).upper())
    return symbols


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
    elif tool_name == "get_dashboard_snapshot":
        return "Checking your dashboard…"
    elif tool_name == "get_market_status":
        return "Checking market session status…"
    return "Analyzing market context…"


class ToolExecutor:
    """
    Manages bounded tool execution for a single Copilot conversation turn.
    Guarantees:
    - Maximum 4 tool calls per turn.
    - Caches identical tool results within the request turn.
    - Strict read-only whitelist.
    """

    def __init__(self, max_tool_calls: int = 4):
        self.max_tool_calls = max_tool_calls
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._executed_calls: List[Dict[str, Any]] = []
        self._activity_labels: List[str] = []

    def _cache_key(self, tool_name: str, args: Dict[str, Any]) -> str:
        sym = args.get("symbol", "")
        symbols = args.get("symbols", [])
        return f"{tool_name}:{sym}:{','.join(sorted(symbols)) if isinstance(symbols, list) else ''}"

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
        extracted_symbols = extract_symbols_from_query(query)

        # Resolve references to "this stock", "this warrant", "mã này" using UI context
        if not extracted_symbols and context:
            if any(k in q_lower for k in ("this stock", "this warrant", "this instrument", "mã này", "con này", "đang xem", "viewing", "current")):
                if context.selectedInstrument and context.selectedInstrument.symbol:
                    extracted_symbols.add(context.selectedInstrument.symbol.upper())
                elif context.selectedSymbol:
                    extracted_symbols.add(context.selectedSymbol.upper())

        # Check for dashboard/multi-symbol queries
        is_dashboard_query = any(k in q_lower for k in DASHBOARD_KEYWORDS)

        # Case 1: Specific symbols mentioned
        if extracted_symbols:
            for sym in list(extracted_symbols)[:2]:  # Limit to 2 symbols per query
                is_cw = (sym.startswith("C") and len(sym) >= 6) or (context and context.selectedInstrument and context.selectedInstrument.instrumentType == "CW")
                
                # Always get live quote
                await self.call_tool("get_quote", {"symbol": sym})

                if is_cw:
                    # For Covered Warrants, get contract terms and quant analytics
                    await self.call_tool("get_instrument", {"symbol": sym})
                    await self.call_tool("get_quant", {"symbol": sym})
                else:
                    # For Stocks, if order book/depth mentioned, get order book
                    if any(k in q_lower for k in ("order book", "sổ lệnh", "depth", "dư mua", "dư bán", "bid ask", "khối lượng")):
                        await self.call_tool("get_order_book", {"symbol": sym})

        # Case 2: Dashboard comparison query (e.g. "which stock is doing best?")
        elif is_dashboard_query:
            watched = context.watchedSymbols if (context and context.watchedSymbols) else None
            await self.call_tool("get_dashboard_snapshot", {"symbols": watched} if watched else {})

        # Case 3: Market status query
        elif any(k in q_lower for k in MARKET_STATUS_KEYWORDS):
            await self.call_tool("get_market_status", {})

        # Default fallback: If user has a selected instrument in UI context, pull its quote
        elif context and context.selectedInstrument and context.selectedInstrument.symbol:
            sym = context.selectedInstrument.symbol.upper()
            await self.call_tool("get_quote", {"symbol": sym})
            if context.selectedInstrument.instrumentType == "CW" or (sym.startswith("C") and len(sym) >= 6):
                await self.call_tool("get_instrument", {"symbol": sym})

        return self._executed_calls

    @property
    def activity_labels(self) -> List[str]:
        return self._activity_labels

    @property
    def executed_calls(self) -> List[Dict[str, Any]]:
        return self._executed_calls
