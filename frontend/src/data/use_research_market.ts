import { useEffect, useSyncExternalStore } from "react";
import type { CoveredWarrant, MarketQuote } from "@/domain/models";
import type { GatewayConnectionState, UpstreamFeedState } from "@/data/providers";
import { providers } from "@/data/providers";
import { backendWebSocketClient } from "@/data/backend/backend_websocket_client";
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

const ws = backendWebSocketClient;

/**
 * Subscribe to the ONE canonical realtime store (BackendWebSocketClient) via
 * useSyncExternalStore. The client owns the quote/warrant maps and connection scalars and
 * mutates them in place; a monotonic `revision` is the snapshot that drives re-renders.
 * Nothing is copied into React state and no new Map is allocated per tick.
 */
export function useResearchMarket() {
  const provider = providers.marketData;

  useEffect(() => {
    provider.connect();
  }, [provider]);

  // Re-render on any observable change (quote / warrant / connection / feed / session).
  useSyncExternalStore(ws.subscribe, ws.getRevision, () => 0);

  return {
    connectionState: ws.getGatewayState(),
    gatewayState: ws.getGatewayState(),
    upstreamFeedState: ws.getUpstreamFeedState(),
    marketSession: ws.getMarketSession(),
    marketSessionActive: ws.isMarketSessionActive(),
    dataMode: config.dataMode,
    isDemo: false,
    warrants: ws.getAllCoveredWarrants(),
    quotes: ws.getAllQuotes(),
    isRealtimeTracked: (symbol: string) => ws.isRealtimeTracked(symbol),
    getWarrant: (symbol: string) => ws.getCoveredWarrant(symbol.toUpperCase()),
    getQuote: (symbol: string) => ws.getQuote(symbol.toUpperCase()),
  };
}

/**
 * Fine-grained per-symbol quote subscription. A consumer using this only re-renders when
 * THAT symbol's quote object is replaced (the client swaps the object on each patch), not
 * on every unrelated tick.
 */
export function useQuote(symbol: string | null | undefined): MarketQuote | undefined {
  const sym = (symbol ?? "").toUpperCase();
  return useSyncExternalStore(
    ws.subscribe,
    () => (sym ? ws.getQuote(sym) : undefined),
    () => undefined
  );
}

export function useCoveredWarrant(symbol: string | null | undefined): CoveredWarrant | undefined {
  const sym = (symbol ?? "").toUpperCase();
  return useSyncExternalStore(
    ws.subscribe,
    () => (sym ? ws.getCoveredWarrant(sym) : undefined),
    () => undefined
  );
}
