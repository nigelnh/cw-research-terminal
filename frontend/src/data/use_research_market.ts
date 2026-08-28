import { useState, useEffect } from "react";
import type { CoveredWarrant, MarketQuote } from "@/domain/models";
import type { GatewayConnectionState, UpstreamFeedState } from "@/data/providers";
import { providers } from "@/data/providers";
import { config } from "@/config";

export interface ResearchMarketState {
  connectionState: GatewayConnectionState;
  gatewayState: GatewayConnectionState;
  upstreamFeedState: UpstreamFeedState;
  marketSession: string;
  marketSessionActive: boolean;
  dataMode: "live" | "hybrid";
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
  const [marketSession, setMarketSession] = useState<string>(
    typeof provider.getMarketSession === "function" ? provider.getMarketSession() : "UNKNOWN"
  );
  const [marketSessionActive, setMarketSessionActive] = useState<boolean>(
    typeof provider.isMarketSessionActive === "function" ? provider.isMarketSessionActive() : false
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

    const unsubSession =
      typeof provider.onMarketSessionChange === "function"
        ? provider.onMarketSessionChange((sess) => {
            setMarketSession(sess.status);
            setMarketSessionActive(sess.active);
          })
        : () => {};

    const unsubQuote = provider.onQuoteUpdate((q) => {
      setQuotes((prev) => {
        const next = new Map(prev);
        next.set(q.symbol, q);
        return next;
      });
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
      unsubSession();
      unsubQuote();
      unsubCw();
    };
  }, [provider]);

  return {
    connectionState,
    gatewayState: connectionState,
    upstreamFeedState,
    marketSession,
    marketSessionActive,
    dataMode: config.dataMode,
    isDemo: false,
    warrants,
    quotes,
    getWarrant: (symbol: string) => warrants.get(symbol.toUpperCase()),
    getQuote: (symbol: string) => quotes.get(symbol.toUpperCase()),
  };
}
