import type { MarketDataProvider, ConnectionState, UpstreamFeedState, MarketDataProviderCapabilities } from "@/data/providers";
import type { CoveredWarrant, MarketQuote } from "@/domain/models";
import { config } from "@/config";
import initialSnapshots from "../fixtures/market_snapshots.json";
import samplePatches from "../fixtures/market_patches.json";

/**
 * MockMarketDataProvider
 * 
 * Simulates real-time market data streaming locally with dynamic symbol subscriptions.
 * Invariant: Emits ticks ONLY for symbols explicitly present in `subscribedSymbols`.
 */
export class MockMarketDataProvider implements MarketDataProvider {
  private state: ConnectionState = "DISCONNECTED";
  private warrantsMap = new Map<string, CoveredWarrant>();
  private quotesMap = new Map<string, MarketQuote>();
  private subscribedSymbols = new Set<string>();

  private stateListeners = new Set<(state: ConnectionState) => void>();
  private upstreamListeners = new Set<(state: UpstreamFeedState) => void>();
  private quoteListeners = new Set<(quote: MarketQuote) => void>();
  private cwListeners = new Set<(cw: CoveredWarrant) => void>();
  private indexListeners = new Set<(data: any) => void>();

  private patchInterval: any = null;
  private patchIndex = 0;

  constructor() {
    this.initFixtures();
  }

  private initFixtures(): void {
    (initialSnapshots as CoveredWarrant[]).forEach((cw) => {
      this.warrantsMap.set(cw.symbol, { ...cw });
      this.quotesMap.set(cw.symbol, { ...cw.quote });
    });
  }

  public getCapabilities(): MarketDataProviderCapabilities {
    return {
      maxRealtimeSymbols: config.maxRealtimeSymbols ?? 33,
      supportsDynamicSubscription: true,
      supportsHistoricalData: true,
      supportsInstrumentSearch: true,
    };
  }

  public getConnectionState(): ConnectionState {
    return this.state;
  }

  public getUpstreamFeedState(): UpstreamFeedState {
    return this.state === "CONNECTED" ? "CONNECTED" : "UNKNOWN";
  }

  public getLatestQuote(symbol: string): MarketQuote | undefined {
    return this.quotesMap.get(symbol.toUpperCase());
  }

  public getLatestCoveredWarrant(symbol: string): CoveredWarrant | undefined {
    return this.warrantsMap.get(symbol.toUpperCase());
  }

  public getAllQuotes(): Map<string, MarketQuote> {
    return this.quotesMap;
  }

  public getAllCoveredWarrants(): Map<string, CoveredWarrant> {
    return this.warrantsMap;
  }

  public getSubscribedSymbols(): Set<string> {
    return new Set(this.subscribedSymbols);
  }

  public subscribeSymbols(symbols: string[]): void {
    symbols.forEach((sym) => {
      const upper = sym.toUpperCase();
      this.subscribedSymbols.add(upper);

      // If connected, emit initial snapshot for newly subscribed symbol
      if (this.state === "CONNECTED") {
        const cw = this.warrantsMap.get(upper);
        if (cw) {
          this.cwListeners.forEach((fn) => fn(cw));
          this.quoteListeners.forEach((fn) => fn(cw.quote));
        }
      }
    });
  }

  public unsubscribeSymbols(symbols: string[]): void {
    symbols.forEach((sym) => {
      this.subscribedSymbols.delete(sym.toUpperCase());
    });
  }

  public onConnectionStateChange(listener: (state: ConnectionState) => void): () => void {
    this.stateListeners.add(listener);
    listener(this.state);
    return () => this.stateListeners.delete(listener);
  }

  public onUpstreamFeedStateChange(listener: (state: UpstreamFeedState) => void): () => void {
    this.upstreamListeners.add(listener);
    listener(this.getUpstreamFeedState());
    return () => this.upstreamListeners.delete(listener);
  }

  public onQuoteUpdate(listener: (quote: MarketQuote) => void): () => void {
    this.quoteListeners.add(listener);
    return () => this.quoteListeners.delete(listener);
  }

  public onCoveredWarrantUpdate(listener: (cw: CoveredWarrant) => void): () => void {
    this.cwListeners.add(listener);
    return () => this.cwListeners.delete(listener);
  }

  public onIndexUpdate(listener: (data: any) => void): () => void {
    this.indexListeners.add(listener);
    return () => this.indexListeners.delete(listener);
  }

  private setState(newState: ConnectionState): void {
    if (this.state !== newState) {
      this.state = newState;
      this.stateListeners.forEach((fn) => fn(newState));
      this.upstreamListeners.forEach((fn) => fn(this.getUpstreamFeedState()));
    }
  }

  public connect(): void {
    if (this.state === "CONNECTED") return;

    this.setState("CONNECTING");

    // Simulate short network delay then connect
    setTimeout(() => {
      this.setState("CONNECTED");

      // Emit initial snapshots only for currently subscribed symbols
      this.subscribedSymbols.forEach((sym) => {
        const cw = this.warrantsMap.get(sym);
        if (cw) {
          this.cwListeners.forEach((fn) => fn(cw));
          this.quoteListeners.forEach((fn) => fn(cw.quote));
        }
      });

      this.indexListeners.forEach((fn) => fn({
        name: "VNINDEX",
        value: 1280.0,
        change: 6.8,
        changePercent: 0.53,
      }));

      // Start periodic simulated patch ticks
      this.startSimulatedPatches();
    }, 150);
  }

  private startSimulatedPatches(): void {
    if (this.patchInterval) return;

    this.patchInterval = setInterval(() => {
      if (this.state !== "CONNECTED") return;

      const patchItem = samplePatches[this.patchIndex % samplePatches.length];
      this.patchIndex++;

      const sym = patchItem.symbol.toUpperCase();

      // INVARIANT: Only emit updates for symbols that are currently subscribed!
      if (!this.subscribedSymbols.has(sym)) {
        return;
      }

      const existing = this.warrantsMap.get(sym);
      if (!existing) return;

      const p = patchItem.patch;
      const q = { ...existing.quote, receivedTimestamp: Date.now() };

      if (p.Traded !== undefined) q.lastPrice = p.Traded;
      if (p.Traded_Qty !== undefined) q.tradedQuantity = p.Traded_Qty;
      if (p.Bid1_Prc !== undefined) q.bidPrice = p.Bid1_Prc;
      if (p.Bid1_Qty !== undefined) q.bidQuantity = p.Bid1_Qty;
      if (p.Ask1_Prc !== undefined) q.askPrice = p.Ask1_Prc;
      if (p.Ask1_Qty !== undefined) q.askQuantity = p.Ask1_Qty;
      if (p.Total_Vol !== undefined) q.totalVolume = p.Total_Vol;
      if (p.Trading_Val !== undefined) q.tradingValue = p.Trading_Val;
      if (p.change !== undefined) q.priceChange = p.change;
      if (p.ChangePercent !== undefined) q.priceChangePercent = p.ChangePercent;

      const updatedCw: CoveredWarrant = {
        ...existing,
        quote: q,
        ivTrade: p.Vol2 !== undefined ? p.Vol2 : existing.ivTrade,
      };

      this.warrantsMap.set(sym, updatedCw);
      this.quotesMap.set(sym, q);

      this.cwListeners.forEach((fn) => fn(updatedCw));
      this.quoteListeners.forEach((fn) => fn(q));
    }, 1000);
  }

  public disconnect(): void {
    if (this.patchInterval) {
      clearInterval(this.patchInterval);
      this.patchInterval = null;
    }
    this.setState("DISCONNECTED");
  }
}

export const mockMarketDataProvider = new MockMarketDataProvider();
