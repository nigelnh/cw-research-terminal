import { config } from "@/config";
import type { GatewayConnectionState, UpstreamFeedState, ConnectionState } from "@/data/providers";
import type { CoveredWarrant, MarketQuote } from "@/domain/models";
import { mapRawSnapshotToCoveredWarrant, applyRawPatchToCoveredWarrant } from "./mappers";

type GatewayStateHandler = (state: GatewayConnectionState) => void;
type UpstreamFeedStateHandler = (state: UpstreamFeedState) => void;

/**
 * Hardened, shared WebSocket client for the Research Platform Market Data Gateway.
 * 
 * Tracks two independent states:
 * 1. `gatewayConnectionState`: Browser WebSocket connectivity to backend gateway (ws://localhost:8787).
 * 2. `upstreamFeedState`: Backend gateway upstream connectivity to active market data feed.
 * 
 * Never treats a successful WebSocket open state as "Live" without verified upstream feed.
 */
export class BackendWebSocketClient {
  private wsUrl: string;
  private ws: WebSocket | null = null;
  private gatewayState: GatewayConnectionState = "DISCONNECTED";
  private upstreamFeedState: UpstreamFeedState = "UNKNOWN";

  private reconnectAttempts = 0;
  private maxReconnectDelay = 15000;
  private baseReconnectDelay = 1000;
  private reconnectTimer: any = null;
  private isIntentionallyClosed = false;

  // In-memory canonical state cache
  private warrantsMap = new Map<string, CoveredWarrant>();
  private quotesMap = new Map<string, MarketQuote>();
  private pendingPatches = new Map<string, any[]>();
  private subscribedSymbols = new Set<string>();

  // Subscriptions & listeners
  private gatewayStateListeners = new Set<GatewayStateHandler>();
  private upstreamFeedListeners = new Set<UpstreamFeedStateHandler>();
  private quoteListeners = new Set<(quote: MarketQuote) => void>();
  private cwListeners = new Set<(cw: CoveredWarrant) => void>();
  private indexListeners = new Set<(data: any) => void>();

  constructor(wsUrl?: string) {
    this.wsUrl = wsUrl || config.wsUrl || "ws://localhost:8787";
  }

  public getConnectionState(): ConnectionState {
    return this.gatewayState;
  }

  public getGatewayState(): GatewayConnectionState {
    return this.gatewayState;
  }

  public getUpstreamFeedState(): UpstreamFeedState {
    return this.upstreamFeedState;
  }

  public getCoveredWarrant(symbol: string): CoveredWarrant | undefined {
    return this.warrantsMap.get(symbol.toUpperCase());
  }

  public getQuote(symbol: string): MarketQuote | undefined {
    return this.quotesMap.get(symbol.toUpperCase());
  }

  public getAllCoveredWarrants(): Map<string, CoveredWarrant> {
    return this.warrantsMap;
  }

  public getAllQuotes(): Map<string, MarketQuote> {
    return this.quotesMap;
  }

  public getSubscribedSymbols(): Set<string> {
    return new Set(this.subscribedSymbols);
  }

  public subscribeSymbols(symbols: string[]): void {
    const toSend: string[] = [];
    symbols.forEach((s) => {
      const upper = s.toUpperCase();
      if (!this.subscribedSymbols.has(upper)) {
        this.subscribedSymbols.add(upper);
        toSend.push(upper);
      }
    });

    if (toSend.length > 0 && this.ws && this.ws.readyState === WebSocket.OPEN) {
      try {
        this.ws.send(JSON.stringify({ type: "subscribe", symbols: toSend }));
      } catch (err) {
        console.warn("[BackendWebSocketClient] Failed to send subscribe message:", err);
      }
    }
  }

  public unsubscribeSymbols(symbols: string[]): void {
    const toSend: string[] = [];
    symbols.forEach((s) => {
      const upper = s.toUpperCase();
      if (this.subscribedSymbols.has(upper)) {
        this.subscribedSymbols.delete(upper);
        toSend.push(upper);
      }
    });

    if (toSend.length > 0 && this.ws && this.ws.readyState === WebSocket.OPEN) {
      try {
        this.ws.send(JSON.stringify({ type: "unsubscribe", symbols: toSend }));
      } catch (err) {
        console.warn("[BackendWebSocketClient] Failed to send unsubscribe message:", err);
      }
    }
  }

  public onConnectionStateChange(listener: GatewayStateHandler): () => void {
    this.gatewayStateListeners.add(listener);
    listener(this.gatewayState);
    return () => this.gatewayStateListeners.delete(listener);
  }

  public onUpstreamFeedStateChange(listener: UpstreamFeedStateHandler): () => void {
    this.upstreamFeedListeners.add(listener);
    listener(this.upstreamFeedState);
    return () => this.upstreamFeedListeners.delete(listener);
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

  private setGatewayState(newState: GatewayConnectionState): void {
    if (this.gatewayState !== newState) {
      this.gatewayState = newState;
      this.gatewayStateListeners.forEach((fn) => fn(newState));
    }
  }

  private setUpstreamFeedState(newState: UpstreamFeedState): void {
    if (this.upstreamFeedState !== newState) {
      this.upstreamFeedState = newState;
      this.upstreamFeedListeners.forEach((fn) => fn(newState));
    }
  }

  public connect(): void {
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      return;
    }

    this.isIntentionallyClosed = false;
    this.setGatewayState(this.reconnectAttempts > 0 ? "RECONNECTING" : "CONNECTING");

    try {
      this.ws = new WebSocket(this.wsUrl);

      this.ws.onopen = () => {
        this.reconnectAttempts = 0;
        this.setGatewayState("CONNECTED");
        // Upstream state remains UNKNOWN or CONNECTING until confirmed by status message or live ticks
        if (this.upstreamFeedState === "DISCONNECTED" || this.upstreamFeedState === "ERROR") {
          this.setUpstreamFeedState("UNKNOWN");
        }

        // Send active desired subscriptions on connect/reconnect
        if (this.subscribedSymbols.size > 0 && this.ws && this.ws.readyState === WebSocket.OPEN) {
          try {
            this.ws.send(JSON.stringify({ type: "subscribe", symbols: Array.from(this.subscribedSymbols) }));
          } catch (err) {
            console.warn("[BackendWebSocketClient] Failed to send initial subscriptions:", err);
          }
        }
      };

      this.ws.onmessage = (event) => {
        try {
          if (!event.data || typeof event.data !== "string") return;
          const raw = JSON.parse(event.data);
          this.handleIncomingMessage(raw);
        } catch (e) {
          console.warn("[BackendWebSocketClient] Ignoring malformed message:", e);
        }
      };

      this.ws.onclose = () => {
        this.ws = null;
        if (!this.isIntentionallyClosed) {
          this.setGatewayState("DISCONNECTED");
          this.setUpstreamFeedState("UNKNOWN");
          this.scheduleReconnect();
        }
      };

      this.ws.onerror = () => {
        this.setGatewayState("ERROR");
        this.setUpstreamFeedState("UNKNOWN");
      };
    } catch {
      this.setGatewayState("ERROR");
      this.setUpstreamFeedState("UNKNOWN");
      this.scheduleReconnect();
    }
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer) return;

    this.reconnectAttempts++;
    const delay = Math.min(
      this.baseReconnectDelay * Math.pow(1.5, this.reconnectAttempts - 1),
      this.maxReconnectDelay
    );

    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay);
  }

  public disconnect(): void {
    this.isIntentionallyClosed = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    this.setGatewayState("DISCONNECTED");
    this.setUpstreamFeedState("UNKNOWN");
  }

  /**
   * Evaluates if an incoming event is stale compared to the current in-memory quote.
   */
  private isEventStale(existing: CoveredWarrant | undefined, incomingSourceTs?: number | null, incomingServerTs?: number | null): boolean {
    if (!existing) return false;
    const currentSourceTs = existing.quote.sourceTimestamp;
    
    // 1. Compare source timestamps if present
    if (incomingSourceTs && currentSourceTs) {
      return incomingSourceTs < currentSourceTs;
    }

    // 2. Fallback to server timestamps if source timestamps absent
    if (incomingServerTs && existing.quote.exchangeTimestamp) {
      return incomingServerTs < existing.quote.exchangeTimestamp;
    }

    return false;
  }

  /**
   * Main message router with defensive parsing, status tracking, and ordering guarantees.
   */
  public handleIncomingMessage(msg: any): void {
    if (!msg || typeof msg !== "object" || !msg.type) {
      return; // Unknown or invalid message format
    }

    switch (msg.type) {
      case "status": {
        // Explicit upstream market feed status from backend gateway
        if (msg.upstream_status === "LIVE" || msg.connected === true) {
          this.setUpstreamFeedState("CONNECTED");
        } else if (
          msg.upstream_status === "CONNECTING" ||
          msg.upstream_status === "RESTARTING" ||
          msg.upstream_status === "READY"
        ) {
          this.setUpstreamFeedState("CONNECTING");
        } else if (
          msg.upstream_status === "UNAVAILABLE" ||
          msg.upstream_status === "ERROR" ||
          msg.connected === false
        ) {
          this.setUpstreamFeedState("DISCONNECTED");
        }
        break;
      }

      case "snapshots": {
        // Bulk snapshot hydration (supporting msg.rows and msg.data)
        const list = Array.isArray(msg.rows) ? msg.rows : (Array.isArray(msg.data) ? msg.data : null);
        if (list) {
          this.setUpstreamFeedState("CONNECTED");
          list.forEach((row: any) => {
            this.processSnapshotRow(row, msg.ts);
          });
        }
        break;
      }

      case "snapshot": {
        // Single symbol full snapshot
        if (msg.row) {
          this.setUpstreamFeedState("CONNECTED");
          this.processSnapshotRow(msg.row, msg.ts);
        }
        break;
      }

      case "patch": {
        // Incremental diff patch
        const sym = String(msg.symbol || msg.patch?.Symbol || "").toUpperCase();
        if (!sym || !msg.patch) return;

        this.setUpstreamFeedState("CONNECTED");

        const incomingSourceTs = msg.patch._ts_source || msg.ts_origin || (msg.patch.ExchangeTime ? Number(msg.patch.ExchangeTime) : null);
        const existing = this.warrantsMap.get(sym);

        // Stale tick rejection check
        if (this.isEventStale(existing, incomingSourceTs, msg.ts)) {
          return;
        }

        if (existing) {
          const updatedCw = applyRawPatchToCoveredWarrant(existing, msg.patch);
          this.warrantsMap.set(sym, updatedCw);
          this.quotesMap.set(sym, updatedCw.quote);
          this.cwListeners.forEach((fn) => fn(updatedCw));
          this.quoteListeners.forEach((fn) => fn(updatedCw.quote));
        } else {
          // Unseen symbol: buffer patch
          if (!this.pendingPatches.has(sym)) {
            this.pendingPatches.set(sym, []);
          }
          this.pendingPatches.get(sym)!.push(msg.patch);

          const placeholder = applyRawPatchToCoveredWarrant(
            {
              symbol: sym,
              issuer: null,
              underlyingSymbol: "",
              underlyingPrice: null,
              strikePrice: 0,
              exerciseRatio: 1.0,
              lastTradingDate: null,
              maturityDate: "",
              quote: {
                symbol: sym,
                lastPrice: null,
                referencePrice: null,
                ceilingPrice: null,
                floorPrice: null,
                openPrice: null,
                highPrice: null,
                lowPrice: null,
                averagePrice: null,
                bidPrice: null,
                bidQuantity: null,
                askPrice: null,
                askQuantity: null,
                tradedQuantity: null,
                totalVolume: null,
                tradingValue: null,
                priceChange: null,
                priceChangePercent: null,
                exchangeTimestamp: null,
                sourceTimestamp: incomingSourceTs,
                receivedTimestamp: Date.now(),
              },
              ivAsk: null,
              ivTrade: null,
              ivBid: null,
            },
            msg.patch
          );
          this.warrantsMap.set(sym, placeholder);
          this.quotesMap.set(sym, placeholder.quote);
          this.cwListeners.forEach((fn) => fn(placeholder));
          this.quoteListeners.forEach((fn) => fn(placeholder.quote));
        }
        break;
      }

      case "analytics_patch": {
        const sym = String(msg.symbol || msg.analytics?.symbol || "").toUpperCase();
        if (!sym || !msg.analytics) break;

        const an = msg.analytics;
        const existing = this.warrantsMap.get(sym);
        if (existing) {
          const g = an.greeks || {};
          const updatedCw: CoveredWarrant = {
            ...existing,
            ivBid: typeof an.iv_bid === "number" ? an.iv_bid : (typeof an.ivBid === "number" ? an.ivBid : existing.ivBid),
            ivTrade: typeof an.iv_trade === "number" ? an.iv_trade : (typeof an.ivTrade === "number" ? an.ivTrade : existing.ivTrade),
            ivAsk: typeof an.iv_ask === "number" ? an.iv_ask : (typeof an.ivAsk === "number" ? an.ivAsk : existing.ivAsk),
            theoreticalPrice: typeof g.theoretical_price === "number" ? g.theoretical_price : (typeof g.theoreticalPrice === "number" ? g.theoreticalPrice : existing.theoreticalPrice),
            delta: typeof g.delta === "number" ? g.delta : existing.delta,
            gamma: typeof g.gamma === "number" ? g.gamma : existing.gamma,
            theta: typeof g.theta === "number" ? g.theta : existing.theta,
            vega: typeof g.vega === "number" ? g.vega : existing.vega,
            rho: typeof g.rho === "number" ? g.rho : existing.rho,
            moneynessRatio: typeof an.moneyness === "number" ? an.moneyness : existing.moneynessRatio,
            historicalVolatility: typeof an.historical_volatility === "number" ? an.historical_volatility : (typeof an.historicalVolatility === "number" ? an.historicalVolatility : existing.historicalVolatility),
          };
          this.warrantsMap.set(sym, updatedCw);
          this.cwListeners.forEach((fn) => fn(updatedCw));
        }
        break;
      }

      case "index_update": {
        if (msg.data && typeof msg.data === "object") {
          this.setUpstreamFeedState("CONNECTED");
          this.indexListeners.forEach((fn) => fn(msg.data));
        }
        break;
      }

      default:
        // Ignore unknown message types gracefully
        break;
    }
  }

  private processSnapshotRow(row: any, serverTs?: number): void {
    if (!row || !row.Symbol) return;
    const sym = String(row.Symbol).toUpperCase();
    const incomingSourceTs = row._ts_source || (row.ExchangeTime ? Number(row.ExchangeTime) : null);
    const existing = this.warrantsMap.get(sym);

    if (this.isEventStale(existing, incomingSourceTs, serverTs)) {
      return; // Drop stale snapshot
    }

    let cw = mapRawSnapshotToCoveredWarrant(row);

    // Apply any buffered patches that arrived before this snapshot
    if (this.pendingPatches.has(sym)) {
      const patches = this.pendingPatches.get(sym)!;
      patches.forEach((p) => {
        cw = applyRawPatchToCoveredWarrant(cw, p);
      });
      this.pendingPatches.delete(sym);
    }

    this.warrantsMap.set(sym, cw);
    this.quotesMap.set(sym, cw.quote);
    this.cwListeners.forEach((fn) => fn(cw));
    this.quoteListeners.forEach((fn) => fn(cw.quote));
  }
}

export const backendWebSocketClient = new BackendWebSocketClient();
