import { config } from "@/config";
import type {
  CompanyProfileResponse,
  CorporateActionsResponse,
  ResearchFeedQuery,
  ResearchFeedResponse,
  ResearchNewsResponse,
} from "@/domain/models";

/** Resolves the current access token (or null when anonymous). Set by the AuthProvider. */
export type AccessTokenProvider = () => string | null | Promise<string | null>;

let accessTokenProvider: AccessTokenProvider | null = null;

/**
 * Register how protected `/api/me/*` requests obtain their bearer token. Public market /
 * quant / history requests never call this and never send an Authorization header.
 */
export function setAccessTokenProvider(fn: AccessTokenProvider | null): void {
  accessTokenProvider = fn;
}

/**
 * The current bearer token, or null when anonymous / not configured. For the request
 * paths that authenticate the same way `BackendClient` does but live outside it - the AI
 * chat SSE `fetch` and the file-extract upload. On those routes a signed-in caller must
 * be keyed to their account (rate-limit tier, visible quota) yet anonymous stays valid,
 * so the header is attached only when a token exists.
 */
export async function getAccessToken(): Promise<string | null> {
  return accessTokenProvider ? await accessTokenProvider() : null;
}

export interface AiQuotaWindow {
  limit: number;
  used: number;
  remaining: number;
  resets_at: number;
}
export interface AiQuota {
  enabled: boolean;
  tier: "guest" | "authenticated";
  per_day?: AiQuotaWindow | null;
  per_minute?: AiQuotaWindow | null;
}

/** Thrown when a protected call has no token, or the backend answered 401/403. */
export class AuthRequiredError extends Error {
  status: number;
  constructor(status = 401, message = "authentication required") {
    super(`HTTP ${status} ${message}`);
    this.name = "AuthRequiredError";
    this.status = status;
  }
}

export class BackendClient {
  private baseUrl: string;

  constructor(baseUrl?: string) {
    this.baseUrl = (
      baseUrl ||
      config.apiUrl ||
      "http://localhost:8000"
    ).replace(/\/$/, "");
  }

  /** Authenticated request for the `/api/me/*` namespace. */
  private async authed<T>(
    method: "GET" | "PUT" | "POST" | "DELETE",
    path: string,
    body?: unknown,
    signal?: AbortSignal,
  ): Promise<T> {
    const token = accessTokenProvider ? await accessTokenProvider() : null;
    if (!token) {
      throw new AuthRequiredError(401, "no session");
    }
    const res = await fetch(`${this.baseUrl}${path}`, {
      method,
      headers: {
        Accept: "application/json",
        Authorization: `Bearer ${token}`,
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal,
    });
    if (res.status === 401 || res.status === 403) {
      throw new AuthRequiredError(res.status);
    }
    if (!res.ok) {
      let detail = "";
      try {
        const errJson = await res.json();
        detail = errJson.detail
          ? JSON.stringify(errJson.detail)
          : JSON.stringify(errJson);
      } catch {
        detail = await res.text();
      }
      throw new Error(`HTTP ${res.status} on ${path}: ${detail}`);
    }
    return res.json();
  }

  /**
   * A GET that attaches the bearer token WHEN there is one but never requires it - for
   * routes where anonymous is valid and the identity only changes the response
   * (`/api/ai/quota`: guest vs signed-in allowance).
   */
  private async getMaybeAuthed<T>(path: string, signal?: AbortSignal): Promise<T> {
    const token = accessTokenProvider ? await accessTokenProvider() : null;
    const res = await fetch(`${this.baseUrl}${path}`, {
      headers: { Accept: "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      signal,
    });
    if (!res.ok) throw new Error(`HTTP ${res.status} on ${path}`);
    return res.json();
  }

  async getAiQuota(signal?: AbortSignal): Promise<AiQuota> {
    return this.getMaybeAuthed<AiQuota>("/api/ai/quota", signal);
  }

  // --- Authenticated: the caller's primary watchlist (/api/me) ---
  async getMyWatchlist(signal?: AbortSignal): Promise<any> {
    return this.authed<any>("GET", "/api/me/watchlist", undefined, signal);
  }

  async putMyWatchlist(items: unknown[], signal?: AbortSignal): Promise<any> {
    return this.authed<any>("PUT", "/api/me/watchlist", { items }, signal);
  }

  private async get<T>(
    path: string,
    params?: Record<string, string | number | undefined>,
    signal?: AbortSignal,
  ): Promise<T> {
    const url = new URL(`${this.baseUrl}${path}`);
    if (params) {
      Object.entries(params).forEach(([key, val]) => {
        if (val !== undefined && val !== null) {
          url.searchParams.append(key, String(val));
        }
      });
    }

    const res = await fetch(url.toString(), {
      headers: {
        Accept: "application/json",
      },
      signal,
    });

    if (!res.ok) {
      let detail = "";
      try {
        const errJson = await res.json();
        detail = errJson.detail || JSON.stringify(errJson);
      } catch {
        detail = await res.text();
      }
      throw new Error(`HTTP ${res.status} on ${path}: ${detail}`);
    }

    return res.json();
  }

  private async post<T>(path: string, body: any): Promise<T> {
    const res = await fetch(`${this.baseUrl}${path}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify(body),
    });

    if (!res.ok) {
      let detail = "";
      try {
        const errJson = await res.json();
        detail = errJson.detail || JSON.stringify(errJson);
      } catch {
        detail = await res.text();
      }
      throw new Error(`HTTP ${res.status} on ${path}: ${detail}`);
    }

    return res.json();
  }

  // Instruments from the registry. Pass status:"ALL" to browse the whole discovered
  // universe (research tab); default is active-only (dashboard).
  async getActiveInstruments(
    issuer?: string,
    underlying?: string,
    search?: string,
    signal?: AbortSignal,
    status?: string,
  ): Promise<any[]> {
    try {
      const params: Record<string, string | undefined> = {
        issuer,
        underlying,
        search,
      };
      if (status) params.status = status;
      else params.active_only = "true";
      const res = await this.get<{
        total: number;
        active_count: number;
        items: any[];
      }>("/api/instruments", params, signal);
      return res.items || [];
    } catch (err) {
      console.warn("[BackendClient] Failed to fetch /api/instruments:", err);
      throw err;
    }
  }

  /** Curated default research/demo universe (verified CWs + underlyings + index). */
  async getDefaultUniverse(
    signal?: AbortSignal,
  ): Promise<{ known_through?: string; items: any[] }> {
    return this.get<{ known_through?: string; items: any[] }>(
      "/api/instruments/default-universe",
      undefined,
      signal,
    );
  }

  /** Fully-resolved dashboard rows with the after-hours temporal fallback (Step 13C). */
  async getDashboardRows(
    symbols: string[],
    signal?: AbortSignal,
  ): Promise<{
    rows: any[];
    as_of: string;
    market_session: string;
    market_session_active: boolean;
    latest_completed_session: string;
    calendar_confidence: string;
  }> {
    return this.get<any>(
      "/api/market/dashboard",
      { symbols: symbols.map((s) => s.toUpperCase()).join(",") },
      signal,
    );
  }

  /** CW analytics companion read; intentionally independent from quote hydration. */
  async getDashboardAnalytics(
    symbols: string[],
    signal?: AbortSignal,
  ): Promise<{
    rows: Array<{
      Symbol: string;
      analytics: Record<string, any> | null;
      provenance: Record<string, any>;
    }>;
    as_of: string;
    market_session: string;
    market_session_active: boolean;
    latest_completed_session: string;
  }> {
    return this.get<any>(
      "/api/market/dashboard/analytics",
      { symbols: symbols.map((s) => s.toUpperCase()).join(",") },
      signal,
    );
  }

  /** Time & sales for one instrument. `side` is derived from the book, never published. */
  async getTradedLog(
    symbol: string,
    limit = 50,
    signal?: AbortSignal,
  ): Promise<{
    symbol: string;
    session_date: string | null;
    count: number;
    side_basis: string;
    market_session: string;
    items: Array<{
      ts: number;
      time: string;
      price: number;
      change: number | null;
      change_percent: number | null;
      volume: number | null;
      side: "B" | "S" | null;
      session_date: string;
    }>;
  }> {
    return this.get<any>(
      `/api/market/trades/${encodeURIComponent(symbol.toUpperCase())}`,
      { limit: String(limit) },
      signal,
    );
  }

  async getStockProfiles(symbols: string[], signal?: AbortSignal): Promise<{ items: Array<{ symbol: string; name: string | null; short_name: string | null; exchange: string | null }> }> {
    return this.get("/api/market/stock-profiles", { symbols: symbols.join(",") }, signal);
  }

  async getMarketOverview(signal?: AbortSignal): Promise<any> {
    return this.get<any>("/api/market/overview", undefined, signal);
  }

  async getInstrumentSpecification(
    symbol: string,
    signal?: AbortSignal,
  ): Promise<any> {
    return this.get<any>(
      `/api/instruments/${encodeURIComponent(symbol.toUpperCase())}`,
      undefined,
      signal,
    );
  }

  async getCoverageMetrics(): Promise<any> {
    return this.get<any>("/api/instruments/metrics/coverage");
  }

  async reconcileSymbols(discoveredSymbols: string[]): Promise<any> {
    const url = `${this.baseUrl}/api/instruments/reconcile`;
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(discoveredSymbols),
    });
    if (!res.ok) throw new Error(`HTTP error ${res.status}`);
    return res.json();
  }

  async getMarketWarrants(
    issuer_name?: string,
    symbol?: string,
    fromDate?: string,
    toDate?: string,
  ): Promise<any[]> {
    return this.get<any[]>("/api/cw/market", {
      issuer_name,
      symbol,
      fromDate,
      toDate,
    });
  }

  async getMarketHistory(
    symbol: string,
    timeframe: string = "1D",
    fromDate?: string,
    toDate?: string,
    adjusted: boolean = true,
    signal?: AbortSignal,
  ): Promise<any[]> {
    return this.get<any[]>(
      `/api/market/history/${encodeURIComponent(symbol)}`,
      {
        timeframe,
        from_date: fromDate,
        to_date: toDate,
        adjusted: adjusted ? "true" : "false",
      },
      signal,
    );
  }

  async getHistoricalCWData(
    symbol?: string,
    fromDate?: string,
    toDate?: string,
  ): Promise<any[]> {
    if (!symbol) return [];
    return this.getMarketHistory(symbol, "1D", fromDate, toDate, true);
  }

  async getComparison(
    stockCode: string,
    fromDate?: string,
    toDate?: string,
  ): Promise<any[]> {
    return this.getMarketHistory(stockCode, "1D", fromDate, toDate, true);
  }

  async getStockCloseHistory(
    symbol: string,
    fromDate?: string,
    toDate?: string,
  ): Promise<any[]> {
    return this.getMarketHistory(symbol, "1D", fromDate, toDate, true);
  }

  async getIndexHistory(
    name: string = "VNINDEX",
    fromDate?: string,
    toDate?: string,
  ): Promise<any[]> {
    return this.getMarketHistory(name, "1D", fromDate, toDate, true);
  }

  async getVolatility(
    symbol: string,
    fromDate?: string,
    toDate?: string,
  ): Promise<any[]> {
    return this.get<any[]>("/api/v1/quant/volatility", {
      symbol,
      fromDate,
      toDate,
    });
  }

  async getBeta(
    symbol: string,
    fromDate?: string,
    toDate?: string,
  ): Promise<any[]> {
    return this.get<any[]>("/api/v1/quant/beta", { symbol, fromDate, toDate });
  }

  async calculatePricing(params: any): Promise<any> {
    return this.post<any>("/api/quant/calculate", params);
  }

  async getWarrantAnalytics(symbol: string): Promise<any> {
    return this.get<any>(`/api/quant/${encodeURIComponent(symbol)}`);
  }

  // --- Research enrichment (Step 14A) ---------------------------------------
  // PostgreSQL-backed reads only. These never trigger an upstream fetch; an
  // un-ingested deployment answers 200 with an empty, well-formed payload.

  async getResearchNews(
    params: {
      symbol?: string;
      q?: string;
      lang?: string;
      limit?: number;
      before?: string;
    } = {},
    signal?: AbortSignal,
  ): Promise<ResearchNewsResponse> {
    return this.get<ResearchNewsResponse>(
      "/api/research/news",
      {
        symbol: params.symbol,
        q: params.q,
        lang: params.lang,
        limit: params.limit,
        before: params.before,
      },
      signal,
    );
  }

  async getResearchNewsFacets(
    lang: string = "vi",
    signal?: AbortSignal,
  ): Promise<{ symbols: string[] }> {
    return this.get<{ symbols: string[] }>(
      "/api/research/news/facets",
      { lang },
      signal,
    );
  }

  /** Unified research feed: HOSE disclosures + company events, cursor-paginated. */
  async getResearchFeed(
    params: ResearchFeedQuery = {},
    signal?: AbortSignal,
  ): Promise<ResearchFeedResponse> {
    return this.get<ResearchFeedResponse>(
      "/api/research/feed",
      {
        symbol: params.symbol,
        symbols: params.symbols?.join(","),
        date_from: params.date_from,
        date_to: params.date_to,
        cursor: params.cursor,
        source: params.source,
        content_type: params.content_type,
        category: params.category,
        event_class: params.event_class,
        q: params.q,
        lang: params.lang,
        limit: params.limit,
        before: params.before,
      },
      signal,
    );
  }

  async getFeedFacets(signal?: AbortSignal): Promise<{ symbols: string[] }> {
    return this.get("/api/research/feed/facets", { lang: "vi" }, signal);
  }

  async getCorporateActions(
    symbol: string,
    limit?: number,
    signal?: AbortSignal,
  ): Promise<CorporateActionsResponse> {
    return this.get<CorporateActionsResponse>(
      `/api/research/corporate-actions/${encodeURIComponent(symbol.toUpperCase())}`,
      { limit },
      signal,
    );
  }

  async getCompanyProfile(
    symbol: string,
    signal?: AbortSignal,
  ): Promise<CompanyProfileResponse> {
    return this.get<CompanyProfileResponse>(
      `/api/research/company/${encodeURIComponent(symbol.toUpperCase())}`,
      undefined,
      signal,
    );
  }
}

export const backendClient = new BackendClient();
