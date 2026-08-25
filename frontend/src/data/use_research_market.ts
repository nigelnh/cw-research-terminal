import { useState, useEffect } from "react";
import type { CoveredWarrant, MarketQuote } from "@/domain/models";
import type { GatewayConnectionState, UpstreamFeedState } from "@/data/providers";
import { providers } from "@/data/providers";
import { config } from "@/config";

export interface ResearchMarketState {
  connectionState: GatewayConnectionState;
  gatewayState: GatewayConnectionState;
  upstreamFeedState: UpstreamFeedState;
  dataMode: "mock" | "live" | "hybrid";
  isDemo: boolean;
  warrants: Map<string, CoveredWarrant>;
  quotes: Map<string, MarketQuote>;
}

/**
 * React hook to consume canonical real-time market data from the active provider.
 * Tracks both browser WebSocket gateway connection and upstream exchange market feed state.
 */
export function useResearchMarket() {
  const provider = providers.marketData;

  const [connectionState, setConnectionState] = useState<GatewayConnectionState>(
    provider.getConnectionState()
  );
  const [upstreamFeedState, setUpstreamFeedState] = useState<UpstreamFeedState>(
    provider.getUpstreamFeedState()
  );
  const [warrants, setWarrants] = useState<Map<string, CoveredWarrant>>(
    new Map(provider.getAllCoveredWarrants())
  );
  const [quotes, setQuotes] = useState<Map<string, MarketQuote>>(
    new Map(provider.getAllQuotes())
  );

  useEffect(() => {
    provider.connect();

    const unsubState = provider.onConnectionStateChange((state) => {
      setConnectionState(state);
    });

    const unsubFeed = provider.onUpstreamFeedStateChange((feedState) => {
      setUpstreamFeedState(feedState);
    });

    const unsubCw = provider.onCoveredWarrantUpdate((cw) => {
      setWarrants((prev) => {
        const next = new Map(prev);
        next.set(cw.symbol, cw);
        return next;
      });
      setQuotes((prev) => {
        const next = new Map(prev);
        next.set(cw.symbol, cw.quote);
        return next;
      });
    });

    return () => {
      unsubState();
      unsubFeed();
      unsubCw();
    };
  }, [provider]);

  return {
    connectionState,
    gatewayState: connectionState,
    upstreamFeedState,
    dataMode: config.dataMode,
    isDemo: config.dataMode === "mock",
    warrants,
    quotes,
    getWarrant: (symbol: string) => warrants.get(symbol.toUpperCase()),
    getQuote: (symbol: string) => quotes.get(symbol.toUpperCase()),
  };
}
