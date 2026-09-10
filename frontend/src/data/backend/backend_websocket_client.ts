import { acceptMarketContext, marketSessionStore } from "@/data/market_session_store";
import { normalizeAnalytics } from "@/data/query/resolve_dashboard_analytics";
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
import { acceptLiveBarMessage } from "./live_bar_store";
import { acceptTradePrintMessage } from "./trade_print_store";

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

function applyAnalyticsToWarrant(
  existing: CoveredWarrant,
  analytics: any,
  emitPulses: boolean,
): CoveredWarrant {
  const g = analytics.greeks || {};
  const numeric = (
    obj: any,
    snake: string,
    camel: string,
    fallback: number | null | undefined,
  ) => {
    const value = snake in obj ? obj[snake] : camel in obj ? obj[camel] : fallback;
    return analytics.is_available === false ||
      analytics.isAvailable === false ||
      typeof value !== "number" ||
      !Number.isFinite(value)
      ? null
      : value;
  };
  const modelInputs = analytics.model_inputs ?? analytics.modelInputs;
  const updated: CoveredWarrant = {
    ...existing,
    analyticsSnapshot: normalizeAnalytics(analytics),
    analyticsCalculatedAt:
      analytics.calculated_at ??
      analytics.calculatedAt ??
      existing.analyticsCalculatedAt ??
      null,
    modelDte:
      modelInputs?.days_to_expiry ?? modelInputs?.daysToExpiry ?? null,
    modelRiskFreeRate:
      modelInputs?.risk_free_rate ?? modelInputs?.riskFreeRate ?? null,
    greeksVolatilitySource:
      g.volatility_source ?? g.volatilitySource ?? null,
    quantAvailable:
      analytics.is_available !== false && analytics.isAvailable !== false,
    ivBid: numeric(analytics, "iv_bid", "ivBid", existing.ivBid),
    ivTrade: numeric(analytics, "iv_trade", "ivTrade", existing.ivTrade),
    ivAsk: numeric(analytics, "iv_ask", "ivAsk", existing.ivAsk),
    theoreticalPrice: numeric(
      g,
      "theoretical_price",
      "theoreticalPrice",
      numeric(
        analytics,
        "theoretical_price",
        "theoreticalPrice",
        existing.theoreticalPrice,
      ),
    ),
    delta: numeric(g, "delta", "delta", existing.delta),
    gamma: numeric(g, "gamma", "gamma", existing.gamma),
    theta: numeric(g, "theta", "theta", existing.theta),
    vega: numeric(g, "vega", "vega", existing.vega),
    rho: numeric(g, "rho", "rho", existing.rho),
    moneynessRatio: numeric(
      analytics,
      "moneyness",
      "moneynessRatio",
      existing.moneynessRatio,
    ),
    moneynessCategory:
      analytics.moneyness_category ??
      analytics.moneynessCategory ??
      existing.moneynessCategory ??
      null,
    contractState:
      analytics.contract_state ??
      analytics.contractState ??
      existing.contractState ??
      null,
    isTradable:
      typeof analytics.is_tradable === "boolean"
        ? analytics.is_tradable
        : typeof analytics.isTradable === "boolean"
          ? analytics.isTradable
          : (existing.isTradable ?? null),
    quantUnavailableReason:
      analytics.is_available === false || analytics.isAvailable === false
        ? (analytics.unavailable_reason ?? analytics.unavailableReason ?? null)
        : null,
    historicalVolatility: numeric(
      analytics,
      "historical_volatility",
      "historicalVolatility",
      existing.historicalVolatility,
    ),
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
  updated.realtimePulses = mergeRealtimePulses(
    existing.realtimePulses,
    existing as unknown as Record<string, number | null | undefined>,
    updated as unknown as Record<string, number | null | undefined>,
    analyticsFields,
    emitPulses,
  );
  return updated;
}

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
  private marketPhase: string = "UNKNOWN";

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

  public getMarketPhase(): string {
    return this.marketPhase;
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
    group: "trade" | "book" | "reference" = "trade",
  ): boolean {
    if (!existingQuote) return false;
    const currentSourceTs = group === "book" ? existingQuote.bookTimestamp
      : group === "reference" ? existingQuote.referenceTimestamp
      : existingQuote.tradeTimestamp ?? existingQuote.sourceTimestamp;

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
        acceptMarketContext(msg);
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
          this.marketPhase = String(msg.market_phase ?? "UNKNOWN");
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
          msg.upstream_status === "READY" ||
          (msg.connected === true && msg.feed_fresh !== false) ||
          (msg.gateway_connected && msg.market_session === "LUNCH_BREAK")
        ) {
          this.setUpstreamFeedState("CONNECTED");
        } else if (msg.upstream_status === "CONNECTING") {
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
        const group = msg.patch._ts_book !== undefined ? "book"
          : msg.patch._ts_reference !== undefined && msg.patch._ts_trade === undefined ? "reference"
          : "trade";
        const groupTs = group === "book" ? msg.patch._ts_book
          : group === "reference" ? msg.patch._ts_reference : incomingSourceTs;
        if (this.isEventStale(existingQuote, groupTs, msg.ts, group)) {
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

      case "bar_patch": {
        acceptLiveBarMessage(msg);
        break;
      }

      case "trade_print": {
        acceptTradePrintMessage(msg);
        break;
      }

      case "analytics_patch": {
        const sym = String(
          msg.symbol || msg.analytics?.symbol || "",
        ).toUpperCase();
        if (!sym || !msg.analytics) break;

        const an = msg.analytics;
        const display = marketSessionStore.getSnapshot().sessionContext?.displaySessionDate;
        const analyticsSession = an.session_date ?? an.sessionDate;
        if (display && analyticsSession !== display) break;
        const existing = this.warrantsMap.get(sym);
        if (existing) {
          const updatedCw = applyAnalyticsToWarrant(
            existing,
            an,
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
      const existingCw = this.warrantsMap.get(sym);
      const inlineAnalytics = row.analytics;
      const display = marketSessionStore.getSnapshot().sessionContext?.displaySessionDate;
      const inlineSession =
        inlineAnalytics?.session_date ?? inlineAnalytics?.sessionDate;
      const hasMatchingInlineAnalytics = Boolean(
        inlineAnalytics && (!display || inlineSession === display),
      );
      if (hasMatchingInlineAnalytics) {
        // Redis-restored analytics travel with the initial quote snapshot, so a hard
        // reload never renders quote/terms first and IV in a later frame.
        cw = applyAnalyticsToWarrant(cw, inlineAnalytics, false);
      }

      // A route change re-subscribes and receives the canonical quote snapshot before
      // the analytics frame. Preserve the already-validated calculation only when that
      // snapshot describes the exact same session and price tuple. This prevents a full
      // snapshot from momentarily replacing IV/Greeks with raw/null values, while a real
      // bid/ask/trade change still clears the old calculation until the backend publishes
      // its new result.
      if (
        !hasMatchingInlineAnalytics &&
        existingCw &&
        this.snapshotMatchesAnalytics(cw, existingCw)
      ) {
        cw = {
          ...cw,
          analyticsCalculatedAt: existingCw.analyticsCalculatedAt,
          analyticsSnapshot: existingCw.analyticsSnapshot,
          modelDte: existingCw.modelDte,
          modelRiskFreeRate: existingCw.modelRiskFreeRate,
          greeksVolatilitySource: existingCw.greeksVolatilitySource,
          quantAvailable: existingCw.quantAvailable,
          ivAsk: existingCw.ivAsk,
          ivTrade: existingCw.ivTrade,
          ivBid: existingCw.ivBid,
          theoreticalPrice: existingCw.theoreticalPrice,
          modelPriceAtIvMid: existingCw.modelPriceAtIvMid,
          theoreticalVolatility: existingCw.theoreticalVolatility,
          theoreticalVolatilitySource: existingCw.theoreticalVolatilitySource,
          delta: existingCw.delta,
          gamma: existingCw.gamma,
          theta: existingCw.theta,
          vega: existingCw.vega,
          rho: existingCw.rho,
          moneynessRatio: existingCw.moneynessRatio,
          moneynessCategory: existingCw.moneynessCategory,
          historicalVolatility: existingCw.historicalVolatility,
          contractState: existingCw.contractState,
          isTradable: existingCw.isTradable,
          quantUnavailableReason: existingCw.quantUnavailableReason,
        };
      }

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

  private snapshotMatchesAnalytics(
    incoming: CoveredWarrant,
    existing: CoveredWarrant,
  ): boolean {
    const analytics = existing.analyticsSnapshot as Record<string, any> | null | undefined;
    const inputs = analytics?.modelInputs ?? analytics?.model_inputs;
    const analyticsSession = analytics?.sessionDate ?? analytics?.session_date;
    const incomingSession = incoming.quote.marketSessionDate;
    if (
      analytics?.isAvailable === false ||
      analytics?.is_available === false ||
      !inputs ||
      !analyticsSession ||
      !incomingSession ||
      analyticsSession !== incomingSession
    ) {
      return false;
    }

    let bid = incoming.quote.bidPrice;
    let ask = incoming.quote.askPrice;
    if (bid != null && ask != null && ask < bid) {
      bid = null;
      ask = null;
    }
    return (
      inputs.market_last === incoming.quote.lastPrice &&
      inputs.market_bid === bid &&
      inputs.market_ask === ask &&
      (incoming.underlyingPrice == null ||
        inputs.underlying_price === incoming.underlyingPrice)
    );
  }
}

export const backendWebSocketClient = new BackendWebSocketClient();
