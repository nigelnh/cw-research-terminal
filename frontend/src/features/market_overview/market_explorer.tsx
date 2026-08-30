import { useMemo } from "react";
import { AppHeader } from "@/components/common/app_header";
import { PersonalDashboard } from "@/features/watchlist/personal_dashboard";
import { ResearchUniverse } from "@/features/stock_research/research_universe";
import { InstrumentPanel } from "@/features/warrant_info/instrument_panel";
import { useWatchlist } from "@/data/watchlist";
import { useResearchMarket, useQuote, useCoveredWarrant } from "@/data/use_research_market";
import { useSearchParam, useNullableSearchParam } from "@/data/url/use_url_state";
import { deriveSelectedInstrument } from "@/data/selected_instrument";
import { useInstrumentSpecs } from "@/data/instruments/use_instrument_specs";
import { useDashboardData } from "@/data/query/use_dashboard_data";
import { computeSpread } from "@/domain/quant_display";
import type { ResearchContextEnvelope } from "@/data/ai/use_ai_chat";

type Tab = "dashboard" | "research";

export function MarketExplorer() {
  const [tabParam, setTabParam] = useSearchParam("tab", "dashboard");
  const activeTab: Tab = tabParam === "research" ? "research" : "dashboard";
  const [selectedSymbol, setSelectedSymbol] = useNullableSearchParam("symbol");
  const [filter, setFilter] = useSearchParam("q", "");

  const { items } = useWatchlist();
  const { getSpec } = useInstrumentSpecs();
  const {
    quotes,
    connectionState,
    upstreamFeedState,
    marketSession,
    marketSessionActive,
    dataMode,
  } = useResearchMarket();
  const dashSymbols = useMemo(() => items.map((i) => i.symbol), [items]);
  const { getRow: getDashRow, meta: dashMeta } = useDashboardData(dashSymbols);

  const selectedQuote = useQuote(selectedSymbol);
  const selectedCw = useCoveredWarrant(selectedSymbol);
  const watchlistItem = useMemo(
    () => items.find((i) => i.symbol.toUpperCase() === (selectedSymbol ?? "").toUpperCase()) ?? null,
    [items, selectedSymbol],
  );
  const selectedSpec = getSpec(selectedSymbol);
  const selected = useMemo(
    () =>
      deriveSelectedInstrument(selectedSymbol, {
        instrumentSpec: selectedSpec,
        watchlistItem,
        quote: selectedQuote,
        cw: selectedCw,
      }),
    [selectedSymbol, selectedSpec, watchlistItem, selectedQuote, selectedCw],
  );

  const selectedDashRow = selected?.symbol ? getDashRow(selected.symbol) : undefined;

  const contextEnvelope = useMemo<ResearchContextEnvelope>(() => {
    let selectedContext = null;
    if (selected) {
      const qv = selected.quote;
      const cw = selected.cw;
      const lastPrice = qv?.lastPrice ?? cw?.quote?.lastPrice;
      const bidPrice = qv?.bidPrice ?? cw?.quote?.bidPrice;
      const askPrice = qv?.askPrice ?? cw?.quote?.askPrice;
      const chgPct = qv?.priceChangePercent ?? cw?.quote?.priceChangePercent;
      const volume = qv?.totalVolume ?? cw?.quote?.totalVolume;
      const underlyingPrice =
        cw?.underlyingPrice ??
        (selected.underlyingSymbol ? quotes.get(selected.underlyingSymbol)?.lastPrice ?? null : null);
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
        spread,
        spreadPercent,
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
      dataState: selectedDashRow?.displayState ?? (marketSessionActive ? "LIVE" : "LAST_SESSION"),
      quoteAsOf:
        selectedDashRow?.provenance?.quote?.asOf ??
        selectedDashRow?.provenance?.quote?.sessionDate ??
        null,
      latestCompletedSession: dashMeta.latestCompletedSession,
      calendarConfidence: dashMeta.calendarConfidence,
    };
  }, [
    activeTab,
    selected,
    selectedDashRow,
    items,
    quotes,
    dataMode,
    connectionState,
    upstreamFeedState,
    marketSession,
    marketSessionActive,
    dashMeta,
  ]);

  const goToTab = (tab: Tab) => setTabParam(tab, "push");
  const selectSymbol = (sym: string | null) => setSelectedSymbol(sym, "push");

  return (
    <div
      style={{
        height: "100vh",
        overflow: "hidden",
        display: "flex",
        flexDirection: "column",
        background: "var(--bg)",
        color: "var(--t-92)",
      }}
    >
      <AppHeader
        activeTab={activeTab}
        onTabChange={goToTab}
        filter={filter}
        onFilterChange={(v) => setFilter(v, "replace")}
        marketSessionActive={marketSessionActive}
      />

      <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}>
        <main style={{ flex: 1, overflow: "auto", padding: "16px 20px", minHeight: 100 }}>
          {activeTab === "dashboard" ? (
            <PersonalDashboard
              onNavigateToUniverse={() => goToTab("research")}
              selectedSymbol={selectedSymbol}
              onSelectSymbol={selectSymbol}
              filter={filter}
            />
          ) : (
            <ResearchUniverse
              onNavigateToDashboard={() => goToTab("dashboard")}
              selectedSymbol={selectedSymbol}
              onSelectSymbol={selectSymbol}
              filter={filter}
            />
          )}
        </main>

        <InstrumentPanel
          instrument={selected}
          dashRow={selectedDashRow}
          marketSessionActive={marketSessionActive}
          context={contextEnvelope}
          onClose={() => selectSymbol(null)}
        />
      </div>
    </div>
  );
}
