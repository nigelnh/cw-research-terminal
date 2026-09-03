import type { MarketQuote, CoveredWarrant } from "@/domain/models";

export type GatewayConnectionState = "CONNECTING" | "CONNECTED" | "DISCONNECTED" | "RECONNECTING" | "ERROR";
export type UpstreamFeedState = "UNKNOWN" | "CONNECTING" | "CONNECTED" | "RECONNECTING" | "STALE" | "DISCONNECTED" | "ERROR";

export type ConnectionState = GatewayConnectionState;

export interface MarketDataProviderCapabilities {
  maxRealtimeSymbols: number | null; // e.g. 33 for limited personal tier, null for unlimited
  supportsDynamicSubscription: boolean;
  supportsHistoricalData: boolean;
  supportsInstrumentSearch: boolean;
}

export interface MarketDataProvider {
  getCapabilities(): MarketDataProviderCapabilities;
  
  getConnectionState(): GatewayConnectionState;
  onConnectionStateChange(listener: (state: GatewayConnectionState) => void): () => void;
  
  getUpstreamFeedState(): UpstreamFeedState;
  onUpstreamFeedStateChange(listener: (state: UpstreamFeedState) => void): () => void;
  
  getLatestQuote(symbol: string): MarketQuote | undefined;
  getLatestCoveredWarrant(symbol: string): CoveredWarrant | undefined;
  
  getAllQuotes(): Map<string, MarketQuote>;
  getAllCoveredWarrants(): Map<string, CoveredWarrant>;
  
  subscribeSymbols(symbols: string[]): void;
  unsubscribeSymbols(symbols: string[]): void;
  syncSubscriptions(symbols: string[]): void;
  
  onQuoteUpdate(listener: (quote: MarketQuote) => void): () => void;
  onCoveredWarrantUpdate(listener: (cw: CoveredWarrant) => void): () => void;
  onIndexUpdate(listener: (indexData: { name: string; value: number; change: number; changePercent: number }) => void): () => void;
  
  getMarketSession?(): string;
  isMarketSessionActive?(): boolean;
  onMarketSessionChange?(listener: (session: { status: string; active: boolean }) => void): () => void;

  connect(): void;
  disconnect(): void;
}
