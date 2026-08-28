import type { MarketDataProvider, ConnectionState, UpstreamFeedState, GatewayConnectionState, MarketDataProviderCapabilities } from "@/data/providers";
import type { MarketQuote, CoveredWarrant } from "@/domain/models";
import { config } from "@/config";
import { BackendWebSocketClient, backendWebSocketClient } from "./backend_websocket_client";

export class BackendMarketDataProvider implements MarketDataProvider {
  private wsClient: BackendWebSocketClient;

  constructor(client?: BackendWebSocketClient) {
    this.wsClient = client || backendWebSocketClient;
  }

  getCapabilities(): MarketDataProviderCapabilities {
    return {
      maxRealtimeSymbols: config.maxRealtimeSymbols ?? 33,
      supportsDynamicSubscription: true,
      supportsHistoricalData: true,
      supportsInstrumentSearch: true,
    };
  }

  getConnectionState(): ConnectionState {
    return this.wsClient.getConnectionState();
  }

  getGatewayState(): GatewayConnectionState {
    return this.wsClient.getGatewayState();
  }

  getUpstreamFeedState(): UpstreamFeedState {
    return this.wsClient.getUpstreamFeedState();
  }

  onConnectionStateChange(listener: (state: ConnectionState) => void): () => void {
    return this.wsClient.onConnectionStateChange(listener);
  }

  onUpstreamFeedStateChange(listener: (state: UpstreamFeedState) => void): () => void {
    return this.wsClient.onUpstreamFeedStateChange(listener);
  }

  getLatestQuote(symbol: string): MarketQuote | undefined {
    return this.wsClient.getQuote(symbol);
  }

  getLatestCoveredWarrant(symbol: string): CoveredWarrant | undefined {
    return this.wsClient.getCoveredWarrant(symbol);
  }

  getAllQuotes(): Map<string, MarketQuote> {
    return this.wsClient.getAllQuotes();
  }

  getAllCoveredWarrants(): Map<string, CoveredWarrant> {
    return this.wsClient.getAllCoveredWarrants();
  }

  subscribeSymbols(symbols: string[]): void {
    this.wsClient.subscribeSymbols(symbols);
  }

  unsubscribeSymbols(symbols: string[]): void {
    this.wsClient.unsubscribeSymbols(symbols);
  }

  syncSubscriptions(symbols: string[]): void {
    this.wsClient.syncSubscriptions(symbols);
  }

  onQuoteUpdate(listener: (quote: MarketQuote) => void): () => void {
    return this.wsClient.onQuoteUpdate(listener);
  }

  onCoveredWarrantUpdate(listener: (cw: CoveredWarrant) => void): () => void {
    return this.wsClient.onCoveredWarrantUpdate(listener);
  }

  onIndexUpdate(listener: (indexData: { name: string; value: number; change: number; changePercent: number }) => void): () => void {
    return this.wsClient.onIndexUpdate(listener);
  }

  getMarketSession(): string {
    return this.wsClient.getMarketSession();
  }

  isMarketSessionActive(): boolean {
    return this.wsClient.isMarketSessionActive();
  }

  onMarketSessionChange(listener: (session: { status: string; active: boolean }) => void): () => void {
    return this.wsClient.onMarketSessionChange(listener);
  }

  connect(): void {
    this.wsClient.connect();
  }

  disconnect(): void {
    this.wsClient.disconnect();
  }
}

export const backendMarketDataProvider = new BackendMarketDataProvider();
