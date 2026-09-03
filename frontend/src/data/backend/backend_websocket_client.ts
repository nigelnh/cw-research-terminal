import { config, normalizeWsUrl } from "@/config";
import type {
  GatewayConnectionState,
  UpstreamFeedState,
  ConnectionState,
} from "@/data/providers";
import type { CoveredWarrant, MarketQuote } from "@/domain/models";
import {
  mapRawSnapshotToCoveredWarrant,
  applyRawPatchToCoveredWarrant,
  mapRawSnapshotToQuote,
  applyRawPatchToQuote,
} from "./mappers";
import { mergeRealtimePulses } from "./mappers/realtime_pulse";

type GatewayStateHandler = (state: GatewayConnectionState) => void;
type UpstreamFeedStateHandler = (state: UpstreamFeedState) => void;

/**
 * Hardened, shared WebSocket client for the Research Platform Market Data Gateway.
 *
 * Tracks two independent states:
 * 1. `gatewayConnectionState`: Browser WebSocket connectivity to backend gateway (ws://localhost:8501/ws/market).
 * 2. `upstreamFeedState`: Backend gateway upstream connectivity to active market data feed.
 *
 * Never treats a successful WebSocket open state as "Live" without verified upstream feed.
 */
const WS_CONNECTING = 0;
const WS_OPEN = 1;

export class BackendWebSocketClient {
  private wsUrl: string;
  private ws: WebSocket | null = null;
  private gatewayState: GatewayConnectionState = "DISCONNECTED";
  private upstreamFeedState: UpstreamFeedState = "UNKNOWN";

  private reconnectAttempts = 0;
  private maxReconnectDelay = 15000;
  private baseReconnectDelay = 1000;
  private reconnectTimer: any = null;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private isIntentionallyClosed = false;

  // In-memory canonical state cache
  private warrantsMap = new Map<string, CoveredWarrant>();
  private quotesMap = new Map<string, MarketQuote>();
  private pendingPatches = new Map<string, any[]>();
  private subscribedSymbols = new Set<string>();
  private pulseReadySymbols = new Set<string>();
  private realtimeUniverse: Set<string> | null = null;
  private untrackedSymbols = new Set<string>();
  private sessionBaselineKey = "";

  // Subscriptions & listeners
  private gatewayStateListeners = new Set<GatewayStateHandler>();
  private upstreamFeedListeners = new Set<UpstreamFeedStateHandler>();
  private sessionListeners = new Set<
    (session: { status: string; active: boolean }) => void
  >();
  private quoteListeners = new Set<(quote: MarketQuote) => void>();
  private cwListeners = new Set<(cw: CoveredWarrant) => void>();
  private indexListeners = new Set<(data: any) => void>();

  // Unified store subscription for useSyncExternalStore consumers. `revision` bumps on
  // ANY observable change (quote, warrant, connection/feed/session state). Consumers read
  // the in-place maps/scalars via the getters; there is exactly ONE quote/warrant store.
  private storeListeners = new Set<() => void>();
  private revision = 0;

  private marketSession: string = "UNKNOWN";
  private marketSessionActive: boolean = false;

  constructor(wsUrl?: string) {
    this.wsUrl = normalizeWsUrl(
      wsUrl || config.wsUrl || "ws://localhost:8501/ws/market",
    );
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

  public getMarketSession(): string {
    return this.marketSession;
  }

  public isMarketSessionActive(): boolean {
    return this.marketSessionActive;
  }

  public onMarketSessionChange(
    listener: (session: { status: string; active: boolean }) => void,
  ): () => void {
    this.sessionListeners.add(listener);
    listener({ status: this.marketSession, active: this.marketSessionActive });
    return () => this.sessionListeners.delete(listener);
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

  public getRealtimeUniverse(): Set<string> | null {
    return this.realtimeUniverse ? new Set(this.realtimeUniverse) : null;
  }

  public isRealtimeTracked(symbol: string): boolean {
    const sym = symbol.toUpperCase();
    if (this.untrackedSymbols.has(sym)) return false;
    return this.realtimeUniverse
      ? this.realtimeUniverse.has(sym)
      : this.subscribedSymbols.has(sym);
  }

  public syncSubscriptions(symbols: string[]): void {
    const clean = Array.from(
      new Set(symbols.map((s) => s.trim().toUpperCase()).filter(Boolean)),
    );
    this.subscribedSymbols = new Set(clean);

    if (this.ws && this.ws.readyState === WS_OPEN) {
      try {
        this.ws.send(
          JSON.stringify({ type: "subscribe", symbols: clean, replace: true }),
        );
      } catch (err) {
        console.warn(
          "[BackendWebSocketClient] Failed to send syncSubscriptions:",
          err,
        );
      }
    }
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

    if (toSend.length > 0 && this.ws && this.ws.readyState === WS_OPEN) {
      try {
        this.ws.send(
          JSON.stringify({
            type: "subscribe",
            symbols: toSend,
            replace: false,
          }),
        );
      } catch (err) {
        console.warn(
          "[BackendWebSocketClient] Failed to send subscribe message:",
          err,
        );
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

    if (toSend.length > 0 && this.ws && this.ws.readyState === WS_OPEN) {
      try {
        this.ws.send(JSON.stringify({ type: "unsubscribe", symbols: toSend }));
      } catch (err) {
        console.warn(
          "[BackendWebSocketClient] Failed to send unsubscribe message:",
          err,
        );
      }
    }
  }

  /** useSyncExternalStore subscribe: fires on any quote/warrant/state change. */
  public subscribe = (listener: () => void): (() => void) => {
    this.storeListeners.add(listener);
    return () => this.storeListeners.delete(listener);
  };

  /** useSyncExternalStore snapshot: a monotonic revision number. */
  public getRevision = (): number => this.revision;

  private bumpRevision(): void {
    this.revision++;
    this.storeListeners.forEach((fn) => fn());
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer !== null) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }

  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.heartbeatTimer = setInterval(() => {
      if (!this.ws || this.ws.readyState !== WS_OPEN) {
        this.stopHeartbeat();
        return;
      }
      try {
        this.ws.send(JSON.stringify({ type: "ping" }));
      } catch {
        this.stopHeartbeat();
      }
    }, 20_000);
  }

  public onConnectionStateChange(listener: GatewayStateHandler): () => void {
    this.gatewayStateListeners.add(listener);
    listener(this.gatewayState);
    return () => this.gatewayStateListeners.delete(listener);
  }

  public onUpstreamFeedStateChange(
    listener: UpstreamFeedStateHandler,
  ): () => void {
    this.upstreamFeedListeners.add(listener);
    listener(this.upstreamFeedState);
    return () => this.upstreamFeedListeners.delete(listener);
  }

  public onQuoteUpdate(listener: (quote: MarketQuote) => void): () => void {
    this.quoteListeners.add(listener);
    return () => this.quoteListeners.delete(listener);
  }

  public onCoveredWarrantUpdate(
    listener: (cw: CoveredWarrant) => void,
  ): () => void {
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
      this.bumpRevision();
    }
  }

  private setUpstreamFeedState(newState: UpstreamFeedState): void {
    if (this.upstreamFeedState !== newState) {
      this.upstreamFeedState = newState;
      this.upstreamFeedListeners.forEach((fn) => fn(newState));
      this.bumpRevision();
    }
  }

  public connect(): void {
    if (
      this.ws &&
      (this.ws.readyState === WS_OPEN || this.ws.readyState === WS_CONNECTING)
    ) {
      return;
    }

    this.isIntentionallyClosed = false;
    this.setGatewayState(
      this.reconnectAttempts > 0 ? "RECONNECTING" : "CONNECTING",
    );

    try {
      this.ws = new WebSocket(this.wsUrl);

      this.ws.onopen = () => {
        this.reconnectAttempts = 0;
        this.setGatewayState("CONNECTED");
        this.startHeartbeat();
        // Upstream state remains UNKNOWN or CONNECTING until confirmed by status message or live ticks
        if (
          this.upstreamFeedState === "DISCONNECTED" ||
          this.upstreamFeedState === "ERROR"
        ) {
          this.setUpstreamFeedState("UNKNOWN");
        }

        // Send active desired subscriptions on connect/reconnect with replacement semantics
        if (
          this.subscribedSymbols.size > 0 &&
          this.ws &&
          this.ws.readyState === WS_OPEN
        ) {
          try {
            this.ws.send(
              JSON.stringify({
                type: "subscribe",
                symbols: Array.from(this.subscribedSymbols),
                replace: true,
              }),
            );
          } catch (err) {
            console.warn(
              "[BackendWebSocketClient] Failed to send initial subscriptions:",
              err,
            );
          }
        }
      };

      this.ws.onmessage = (event) => {
        try {
          if (!event.data || typeof event.data !== "string") return;
          const raw = JSON.parse(event.data);
          this.handleIncomingMessage(raw);
        } catch (e) {
          console.warn(
            "[BackendWebSocketClient] Ignoring malformed message:",
            e,
          );
        }
      };

      this.ws.onclose = () => {
        this.stopHeartbeat();
        this.ws = null;
        this.pulseReadySymbols.clear();
        if (!this.isIntentionallyClosed) {
          this.setGatewayState("RECONNECTING");
          this.setUpstreamFeedState("RECONNECTING");
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
      this.maxReconnectDelay,
    );

    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay);
  }

  public disconnect(): void {
    this.isIntentionallyClosed = true;
    this.stopHeartbeat();
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
  private isEventStale(
    existingQuote: MarketQuote | undefined,
    incomingSourceTs?: number | null,
    incomingServerTs?: number | null,
  ): boolean {
    if (!existingQuote) return false;
    const currentSourceTs = existingQuote.sourceTimestamp;

    // 1. Compare source timestamps if present
    if (incomingSourceTs && currentSourceTs) {
      return incomingSourceTs < currentSourceTs;
    }

    // 2. Fallback to server timestamps if source timestamps absent
    if (incomingServerTs && existingQuote.exchangeTimestamp) {
      return incomingServerTs < existingQuote.exchangeTimestamp;
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
    this.routeIncomingMessage(msg);
    // Single revision bump after routing so useSyncExternalStore consumers re-render once
    // per inbound frame regardless of how many maps/scalars it touched.
    this.bumpRevision();
  }

  private routeIncomingMessage(msg: any): void {
    switch (msg.type) {
      case "status": {
        const nextSessionKey = String(
          msg.market_session_date ?? msg.session_date ?? msg.market_session ?? "",
        );
        if (
          this.sessionBaselineKey &&
          nextSessionKey &&
          nextSessionKey !== this.sessionBaselineKey
        ) {
          this.pulseReadySymbols.clear();
        }
        if (nextSessionKey) this.sessionBaselineKey = nextSessionKey;

        const rawUniverse =
          msg.realtime_universe_symbols ??
          msg.universe_symbols ??
          msg.allowed_symbols;
        if (Array.isArray(rawUniverse)) {
          this.realtimeUniverse = new Set(
            rawUniverse.map((value: unknown) => String(value).toUpperCase()),
          );
          this.untrackedSymbols = new Set(
            [...this.subscribedSymbols].filter(
              (symbol) => !this.realtimeUniverse!.has(symbol),
            ),
          );
        }

        if (msg.market_session) {
          this.marketSession = String(msg.market_session);
          this.marketSessionActive = Boolean(msg.market_session_active);
          this.sessionListeners.forEach((fn) =>
            fn({
              status: this.marketSession,
              active: this.marketSessionActive,
            }),
          );
        }

        // Explicit upstream market feed status from backend gateway
        if (
          msg.upstream_status === "RESTARTING" ||
          msg.upstream_status === "RECONNECTING"
        ) {
          this.setUpstreamFeedState("RECONNECTING");
        } else if (msg.feed_fresh === false && Boolean(msg.market_session_active)) {
          this.setUpstreamFeedState("STALE");
        } else if (
          msg.upstream_status === "LIVE" ||
          (msg.connected === true && msg.feed_fresh !== false) ||
          (msg.gateway_connected && msg.market_session === "LUNCH_BREAK")
        ) {
          this.setUpstreamFeedState("CONNECTED");
        } else if (
          msg.upstream_status === "CONNECTING" ||
          msg.upstream_status === "READY"
        ) {
          this.setUpstreamFeedState("CONNECTING");
        } else if (
          msg.upstream_status === "UNAVAILABLE" ||
          msg.upstream_status === "ERROR"
        ) {
          this.setUpstreamFeedState("DISCONNECTED");
        } else if (msg.connected === false && !msg.gateway_connected) {
          this.setUpstreamFeedState("DISCONNECTED");
        }
        break;
      }

      case "snapshots": {
        // Bulk snapshot hydration (supporting msg.rows and msg.data)
        const list = Array.isArray(msg.rows)
          ? msg.rows
          : Array.isArray(msg.data)
            ? msg.data
            : null;
        if (list) {
          list.forEach((row: any) => {
            this.processSnapshotRow(row, msg.ts);
          });
        }
        break;
      }

      case "snapshot": {
        // Single symbol full snapshot
        if (msg.row) {
          this.processSnapshotRow(msg.row, msg.ts);
        }
        break;
      }

      case "patch": {
        // Incremental diff patch
        const sym = String(msg.symbol || msg.patch?.Symbol || "").toUpperCase();
        if (!sym || !msg.patch) return;

        const incomingSourceTs =
          msg.patch._ts_source ||
          msg.ts_origin ||
          (msg.patch.ExchangeTime ? Number(msg.patch.ExchangeTime) : null);
        const existingCw = this.warrantsMap.get(sym);
        const existingQuote = this.quotesMap.get(sym);

        const patchSessionKey = String(
          msg.patch._market_session_date ?? msg.patch.market_session_date ?? "",
        );
        if (
          this.sessionBaselineKey &&
          patchSessionKey &&
          patchSessionKey !== this.sessionBaselineKey
        ) {
          this.pulseReadySymbols.clear();
        }
        if (patchSessionKey) this.sessionBaselineKey = patchSessionKey;

        // Stale tick rejection check
        if (this.isEventStale(existingQuote, incomingSourceTs, msg.ts)) {
          return;
        }

        const emitPulses = this.pulseReadySymbols.has(sym);
        const updatedQuote = applyRawPatchToQuote(
          existingQuote,
          sym,
          msg.patch,
          incomingSourceTs,
          { emitPulses },
        );
        this.quotesMap.set(sym, updatedQuote);
        this.quoteListeners.forEach((fn) => fn(updatedQuote));

        // Only populate/update warrantsMap if symbol is actually a Covered Warrant
        const isCwSymbol = sym.startsWith("C") && sym.length >= 6;
        if (existingCw || isCwSymbol) {
          if (!existingCw) {
            if (!this.pendingPatches.has(sym)) {
              this.pendingPatches.set(sym, []);
            }
            this.pendingPatches.get(sym)!.push(msg.patch);
          }
          const baseCw: CoveredWarrant = existingCw || {
            symbol: sym,
            issuer: null,
            underlyingSymbol: "",
            underlyingPrice: null,
            strikePrice: null,
            exerciseRatio: null,
            lastTradingDate: null,
            maturityDate: "",
            quote: updatedQuote,
            ivAsk: null,
            ivTrade: null,
            ivBid: null,
          };
          const updatedCw = applyRawPatchToCoveredWarrant(baseCw, msg.patch, {
            emitPulses,
          });
          this.warrantsMap.set(sym, updatedCw);
          this.cwListeners.forEach((fn) => fn(updatedCw));
        }
        this.pulseReadySymbols.add(sym);
        break;
      }

      case "analytics_patch": {
        const sym = String(
          msg.symbol || msg.analytics?.symbol || "",
        ).toUpperCase();
        if (!sym || !msg.analytics) break;

        const an = msg.analytics;
        const existing = this.warrantsMap.get(sym);
        if (existing) {
          const g = an.greeks || {};
          const numeric = (
            obj: any,
            snake: string,
            camel: string,
            fallback: number | null | undefined,
          ) => {
            const value =
              snake in obj ? obj[snake] : camel in obj ? obj[camel] : fallback;
            return an.is_available === false ||
              typeof value !== "number" ||
              !Number.isFinite(value)
              ? null
              : value;
          };
          const updatedCw: CoveredWarrant = {
            ...existing,
            analyticsCalculatedAt:
              an.calculated_at ?? existing.analyticsCalculatedAt ?? null,
            modelDte: an.model_inputs?.days_to_expiry ?? null,
            modelRiskFreeRate: an.model_inputs?.risk_free_rate ?? null,
            greeksVolatilitySource: g.volatility_source ?? null,
            quantAvailable: an.is_available !== false,
            ivBid: numeric(an, "iv_bid", "ivBid", existing.ivBid),
            ivTrade: numeric(an, "iv_trade", "ivTrade", existing.ivTrade),
            ivAsk: numeric(an, "iv_ask", "ivAsk", existing.ivAsk),
            theoreticalPrice: numeric(
              g,
              "theoretical_price",
              "theoreticalPrice",
              existing.theoreticalPrice,
            ),
            delta: numeric(g, "delta", "delta", existing.delta),
            gamma: numeric(g, "gamma", "gamma", existing.gamma),
            theta: numeric(g, "theta", "theta", existing.theta),
            vega: numeric(g, "vega", "vega", existing.vega),
            rho: numeric(g, "rho", "rho", existing.rho),
            moneynessRatio: numeric(
              an,
              "moneyness",
              "moneynessRatio",
              existing.moneynessRatio,
            ),
            moneynessCategory:
              an.moneyness_category ??
              an.moneynessCategory ??
              existing.moneynessCategory ??
              null,
            contractState:
              an.contract_state ??
              an.contractState ??
              existing.contractState ??
              null,
            isTradable:
              typeof an.is_tradable === "boolean"
                ? an.is_tradable
                : typeof an.isTradable === "boolean"
                  ? an.isTradable
                  : (existing.isTradable ?? null),
            quantUnavailableReason:
              an.is_available === false
                ? (an.unavailable_reason ?? null)
                : null,
            historicalVolatility:
              typeof an.historical_volatility === "number"
                ? an.historical_volatility
                : typeof an.historicalVolatility === "number"
                  ? an.historicalVolatility
                  : existing.historicalVolatility,
          };
          const analyticsFields = [
            "ivBid",
            "ivTrade",
            "ivAsk",
            "theoreticalPrice",
            "delta",
            "gamma",
            "theta",
            "vega",
            "rho",
            "moneynessRatio",
            "historicalVolatility",
          ];
          updatedCw.realtimePulses = mergeRealtimePulses(
            existing.realtimePulses,
            existing as unknown as Record<string, number | null | undefined>,
            updatedCw as unknown as Record<string, number | null | undefined>,
            analyticsFields,
            this.pulseReadySymbols.has(sym),
          );
          this.warrantsMap.set(sym, updatedCw);
          this.cwListeners.forEach((fn) => fn(updatedCw));
          this.pulseReadySymbols.add(sym);
        }
        break;
      }

      case "subscription_ack":
      case "subscribed": {
        const outside =
          msg.outside_symbols ??
          msg.unavailable_symbols ??
          msg.outside_universe ??
          msg.rejected_symbols ??
          [];
        if (Array.isArray(outside)) {
          outside.forEach((value: unknown) =>
            this.untrackedSymbols.add(String(value).toUpperCase()),
          );
        }
        const accepted = msg.accepted_symbols ?? msg.symbols ?? [];
        if (Array.isArray(accepted)) {
          accepted.forEach((value: unknown) =>
            this.untrackedSymbols.delete(String(value).toUpperCase()),
          );
        }
        break;
      }

      case "index_update": {
        if (msg.data && typeof msg.data === "object") {
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
    const incomingSourceTs =
      row._ts_source || (row.ExchangeTime ? Number(row.ExchangeTime) : null);
    const existingQuote = this.quotesMap.get(sym);

    if (this.isEventStale(existingQuote, incomingSourceTs, serverTs)) {
      return; // Drop stale snapshot
    }

    const isCwSymbol = sym.startsWith("C") && sym.length >= 6;
    const isCwType =
      row.instrument_type === "CW" ||
      row.InstrumentType === "CW" ||
      !!row.Under_Symbol ||
      !!row.Underlying;

    if (isCwSymbol || isCwType) {
      let cw = mapRawSnapshotToCoveredWarrant(row);

      // Apply any buffered patches that arrived before this snapshot
      if (this.pendingPatches.has(sym)) {
        const patches = this.pendingPatches.get(sym)!;
        patches.forEach((p) => {
          cw = applyRawPatchToCoveredWarrant(cw, p, { emitPulses: false });
        });
        this.pendingPatches.delete(sym);
      }

      this.warrantsMap.set(sym, cw);
      this.quotesMap.set(sym, cw.quote);
      this.cwListeners.forEach((fn) => fn(cw));
      this.quoteListeners.forEach((fn) => fn(cw.quote));
    } else {
      const quote = mapRawSnapshotToQuote(row);
      this.quotesMap.set(sym, quote);
      this.quoteListeners.forEach((fn) => fn(quote));
    }
    this.pulseReadySymbols.add(sym);
  }
}

export const backendWebSocketClient = new BackendWebSocketClient();
