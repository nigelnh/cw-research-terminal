import { useMemo } from "react";
import { TopNav } from "@/components/common/top_nav";
import { PersonalDashboard } from "@/features/watchlist/personal_dashboard";
import { ResearchUniverse } from "@/features/stock_research/research_universe";
import { AiAssistantBubble } from "@/features/ai_assistant/ai_assistant_bubble";
import { useWatchlist } from "@/data/watchlist";
import { useResearchMarket, useQuote, useCoveredWarrant } from "@/data/use_research_market";
import { useSearchParam, useNullableSearchParam } from "@/data/url/use_url_state";
import { deriveSelectedInstrument } from "@/data/selected_instrument";
import { computeSpread } from "@/domain/quant_display";
import type { ResearchContextEnvelope } from "@/data/ai/use_ai_chat";

type Tab = "dashboard" | "research";

export function MarketExplorer() {
  // Shareable/navigation state lives in the URL: ?tab= & ?symbol=
  const [tabParam, setTabParam] = useSearchParam("tab", "dashboard");
  const activeTab: Tab = tabParam === "research" ? "research" : "dashboard";
  const [selectedSymbol, setSelectedSymbol] = useNullableSearchParam("symbol");

  const { items } = useWatchlist();
  const { quotes, connectionState, upstreamFeedState, marketSession, marketSessionActive, dataMode } =
    useResearchMarket();

  // Derived (never stored): the selected instrument's contract metadata comes from the
  // watchlist; its live quote/analytics come from the realtime store.
  const selectedQuote = useQuote(selectedSymbol);
  const selectedCw = useCoveredWarrant(selectedSymbol);
  const watchlistItem = useMemo(
    () => items.find((i) => i.symbol.toUpperCase() === (selectedSymbol ?? "").toUpperCase()) ?? null,
    [items, selectedSymbol]
  );
  const selected = useMemo(
    () => deriveSelectedInstrument(selectedSymbol, { watchlistItem, quote: selectedQuote, cw: selectedCw }),
    [selectedSymbol, watchlistItem, selectedQuote, selectedCw]
  );

  const contextEnvelope = useMemo<ResearchContextEnvelope>(() => {
    let selectedContext = null;
    if (selected) {
      const q = selected.quote;
      const cw = selected.cw;
      const lastPrice = q?.lastPrice ?? cw?.quote?.lastPrice;
      const bidPrice = q?.bidPrice ?? cw?.quote?.bidPrice;
      const askPrice = q?.askPrice ?? cw?.quote?.askPrice;
      const chgPct = q?.priceChangePercent ?? cw?.quote?.priceChangePercent;
      const volume = q?.totalVolume ?? cw?.quote?.totalVolume;
      const underlyingPrice =
        cw?.underlyingPrice ??
        (selected.underlyingSymbol ? quotes.get(selected.underlyingSymbol)?.lastPrice ?? null : null);
      // Spread: the ONE canonical convention (ask - bid) / mid. Moneyness: canonical from the
      // backend quant engine - the client never derives S/K, so if the quant gate rejected
      // this contract's metadata the AI sees `moneyness: null` exactly as the UI shows "—".
      const { abs: spread, pct: spreadPercent } = computeSpread(bidPrice, askPrice);

      selectedContext = {
        symbol: selected.symbol,
        instrumentType: selected.instrumentType,
        issuer: selected.issuer ?? null,
        underlyingSymbol: selected.underlyingSymbol ?? null,
        strikePrice: selected.strikePrice ?? null,
        exerciseRatio: selected.exerciseRatio ?? null,
        maturityDate: selected.maturityDate ?? null,
        lastTradingDate: selected.lastTradingDate ?? null,
        underlyingPrice: underlyingPrice ?? null,
        bidPrice: bidPrice ?? null,
        askPrice: askPrice ?? null,
        lastPrice: lastPrice ?? null,
        priceChangePercent: chgPct ?? null,
        spread: spread,
        spreadPercent: spreadPercent,
        volume: volume ?? null,
        ivBid: cw?.ivBid ?? null,
        ivTrade: cw?.ivTrade ?? null,
        ivAsk: cw?.ivAsk ?? null,
        moneyness: typeof cw?.moneynessRatio === "number" ? cw.moneynessRatio : null,
        moneynessLabel: cw?.moneynessCategory ?? null,
        contractState: cw?.contractState ?? null,
        quantAvailable: typeof cw?.ivBid === "number" || typeof cw?.delta === "number",
      };
    }

    const realtimeStatusLabel =
      connectionState === "DISCONNECTED" || connectionState === "ERROR"
        ? "Backend offline"
        : connectionState === "RECONNECTING"
        ? "Reconnecting feed"
        : marketSession === "LUNCH_BREAK"
        ? "Lunch break"
        : marketSession === "CLOSED_PRE_OPEN" ||
          marketSession === "CLOSED_POST_MARKET" ||
          marketSession === "CLOSED_WEEKEND"
        ? "Market closed"
        : upstreamFeedState === "CONNECTED" || marketSessionActive
        ? "Market open"
        : upstreamFeedState === "CONNECTING"
        ? "Connecting feed"
        : "Feed unavailable";

    return {
      activePage: activeTab,
      selectedInstrument: selectedContext,
      watchlist: items.map((i) => i.symbol),
      realtimeStatus: realtimeStatusLabel,
      dataMode,
      marketSession,
      marketSessionActive,
      quoteDisplayEligible: marketSessionActive,
    };
  }, [
    activeTab,
    selected,
    items,
    quotes,
    dataMode,
    connectionState,
    upstreamFeedState,
    marketSession,
    marketSessionActive,
  ]);

  const goToTab = (tab: Tab) => setTabParam(tab, "push");
  const selectSymbol = (sym: string | null) => setSelectedSymbol(sym, "push");

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        minHeight: "100vh",
        height: "100%",
        backgroundColor: "var(--background)",
        color: "var(--foreground)",
        fontFamily: "var(--font-sans)",
        overflowY: "auto",
      }}
    >
      <TopNav activeTab={activeTab} onTabChange={goToTab} />

      <main style={{ flex: 1, padding: "28px", maxWidth: "1600px", width: "100%", margin: "0 auto" }}>
        {activeTab === "dashboard" ? (
          <PersonalDashboard
            onNavigateToUniverse={() => goToTab("research")}
            selectedSymbol={selectedSymbol}
            onSelectSymbol={selectSymbol}
          />
        ) : (
          <ResearchUniverse
            onNavigateToDashboard={() => goToTab("dashboard")}
            selectedSymbol={selectedSymbol}
            onSelectSymbol={selectSymbol}
          />
        )}
      </main>

      <AiAssistantBubble context={contextEnvelope} />
    </div>
  );
}
