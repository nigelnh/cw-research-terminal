import { useState, useMemo } from "react";
import { TopNav } from "../common/top_nav";
import { PersonalDashboard } from "../Dashboard/personal_dashboard";
import { ResearchUniverse } from "../Universe/research_universe";
import { AiAssistantBubble } from "../common/ai_assistant_bubble";
import { useWatchlist } from "@/data/watchlist";
import { useResearchMarket } from "@/data/use_research_market";
import type { ResearchContextEnvelope } from "@/data/ai/use_ai_chat";

export function MarketExplorer() {
  const [activeTab, setActiveTab] = useState<"dashboard" | "research">("dashboard");
  const [selectedInstrument, setSelectedInstrument] = useState<any | null>(null);

  const { items } = useWatchlist();
  const { quotes, warrants, dataMode, connectionState, upstreamFeedState } = useResearchMarket();

  // Construct compact, canonical research context envelope (zero DOM scraping)
  const contextEnvelope = useMemo<ResearchContextEnvelope>(() => {
    let selectedContext = null;

    if (selectedInstrument) {
      const sym = selectedInstrument.symbol;
      const q = selectedInstrument.quote || quotes.get(sym);
      const cw = selectedInstrument.cw || warrants.get(sym);

      const lastPrice = q?.lastPrice ?? cw?.quote?.lastPrice;
      const bidPrice = q?.bidPrice ?? cw?.quote?.bidPrice;
      const askPrice = q?.askPrice ?? cw?.quote?.askPrice;
      const chgPct = q?.priceChangePercent ?? cw?.quote?.priceChangePercent;
      const volume = q?.totalVolume ?? cw?.quote?.totalVolume;
      const underlyingPrice =
        cw?.underlyingPrice ??
        (selectedInstrument.underlyingSymbol ? quotes.get(selectedInstrument.underlyingSymbol)?.lastPrice : null);

      const moneynessRatio =
        underlyingPrice && selectedInstrument.strikePrice
          ? (underlyingPrice / selectedInstrument.strikePrice) * 100
          : null;

      const spread = bidPrice !== undefined && askPrice !== undefined ? askPrice - bidPrice : null;
      const spreadPercent = spread !== null && lastPrice ? (spread / lastPrice) * 100 : null;

      selectedContext = {
        symbol: sym,
        instrumentType: selectedInstrument.instrumentType || "CW",
        issuer: selectedInstrument.issuer || cw?.issuer || null,
        underlyingSymbol: selectedInstrument.underlyingSymbol || cw?.underlyingSymbol || null,
        strikePrice: selectedInstrument.strikePrice || cw?.strikePrice || null,
        exerciseRatio: selectedInstrument.exerciseRatio || cw?.exerciseRatio || null,
        maturityDate: selectedInstrument.maturityDate || cw?.maturityDate || null,
        lastTradingDate: selectedInstrument.lastTradingDate || cw?.lastTradingDate || null,
        underlyingPrice: underlyingPrice ?? null,
        bidPrice: bidPrice ?? null,
        askPrice: askPrice ?? null,
        lastPrice: lastPrice ?? null,
        priceChangePercent: chgPct ?? null,
        spread: spread ?? null,
        spreadPercent: spreadPercent ?? null,
        volume: volume ?? null,
        ivBid: cw?.ivBid ?? null,
        ivTrade: cw?.ivTrade ?? null,
        ivAsk: cw?.ivAsk ?? null,
        moneyness: moneynessRatio ?? null,
        moneynessLabel: moneynessRatio ? (moneynessRatio >= 100 ? "ITM" : "OTM") : null,
      };
    }

    const realtimeStatusLabel =
      dataMode === "mock"
        ? "Demo"
        : upstreamFeedState === "CONNECTED"
        ? "Live"
        : upstreamFeedState === "CONNECTING"
        ? "Connecting Feed"
        : connectionState === "DISCONNECTED"
        ? "Disconnected"
        : "Feed Unavailable";

    return {
      activePage: activeTab,
      selectedInstrument: selectedContext,
      watchlist: items.map((i) => i.symbol),
      realtimeStatus: realtimeStatusLabel,
      dataMode,
    };
  }, [activeTab, selectedInstrument, items, quotes, warrants, dataMode, connectionState, upstreamFeedState]);

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
      {/* Top Minimal Navigation Bar */}
      <TopNav
        activeTab={activeTab}
        onTabChange={(tab) => setActiveTab(tab)}
      />

      {/* Main Workspace Page */}
      <main
        style={{
          flex: 1,
          padding: "28px",
          maxWidth: "1600px",
          width: "100%",
          margin: "0 auto",
        }}
      >
        {activeTab === "dashboard" ? (
          <PersonalDashboard
            onNavigateToUniverse={() => setActiveTab("research")}
            selectedInstrument={selectedInstrument}
            onSelectInstrument={setSelectedInstrument}
          />
        ) : (
          <ResearchUniverse
            onNavigateToDashboard={() => setActiveTab("dashboard")}
            selectedInstrument={selectedInstrument}
            onSelectInstrument={setSelectedInstrument}
          />
        )}
      </main>

      {/* Floating AI Assistant Shell with Context */}
      <AiAssistantBubble context={contextEnvelope} />
    </div>
  );
}
