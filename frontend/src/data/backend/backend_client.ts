import { config } from "@/config";

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
    this.baseUrl = (baseUrl || config.apiUrl || "http://localhost:8000").replace(/\/$/, "");
  }

  /** Authenticated request for the `/api/me/*` namespace. */
  private async authed<T>(
    method: "GET" | "PUT" | "POST" | "DELETE",
    path: string,
    body?: unknown,
    signal?: AbortSignal
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
        detail = errJson.detail ? JSON.stringify(errJson.detail) : JSON.stringify(errJson);
      } catch {
        detail = await res.text();
      }
      throw new Error(`HTTP ${res.status} on ${path}: ${detail}`);
    }
    return res.json();
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
    signal?: AbortSignal
  ): Promise<T> {
    const url = new URL(`${this.baseUrl}${path}`);
    if (params) {
      Object.entries(params).forEach(([key, val]) => {
        if (val !== undefined && val !== null && val !== "") {
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

  // Active Instruments from Instrument Registry
  async getActiveInstruments(
    issuer?: string,
    underlying?: string,
    search?: string,
    signal?: AbortSignal
  ): Promise<any[]> {
    try {
      const res = await this.get<{ total: number; active_count: number; items: any[] }>(
        "/api/instruments",
        { issuer, underlying, search, active_only: "true" },
        signal
      );
      return res.items || [];
    } catch (err) {
      console.warn("[BackendClient] Failed to fetch /api/instruments:", err);
      throw err;
    }
  }

  async getInstrumentSpecification(symbol: string, signal?: AbortSignal): Promise<any> {
    return this.get<any>(`/api/instruments/${encodeURIComponent(symbol.toUpperCase())}`, undefined, signal);
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

  async getMarketWarrants(issuer_name?: string, symbol?: string, fromDate?: string, toDate?: string): Promise<any[]> {
    return this.get<any[]>("/api/cw/market", { issuer_name, symbol, fromDate, toDate });
  }

  async getMarketHistory(
    symbol: string,
    timeframe: string = "1D",
    fromDate?: string,
    toDate?: string,
    adjusted: boolean = true,
    signal?: AbortSignal
  ): Promise<any[]> {
    return this.get<any[]>(
      `/api/market/history/${encodeURIComponent(symbol)}`,
      {
        timeframe,
        from_date: fromDate,
        to_date: toDate,
        adjusted: adjusted ? "true" : "false",
      },
      signal
    );
  }

  async getHistoricalCWData(symbol?: string, fromDate?: string, toDate?: string): Promise<any[]> {
    if (!symbol) return [];
    return this.getMarketHistory(symbol, "1D", fromDate, toDate, true);
  }

  async getComparison(stockCode: string, fromDate?: string, toDate?: string): Promise<any[]> {
    return this.getMarketHistory(stockCode, "1D", fromDate, toDate, true);
  }

  async getStockCloseHistory(symbol: string, fromDate?: string, toDate?: string): Promise<any[]> {
    return this.getMarketHistory(symbol, "1D", fromDate, toDate, true);
  }

  async getIndexHistory(name: string = "VNINDEX", fromDate?: string, toDate?: string): Promise<any[]> {
    return this.getMarketHistory(name, "1D", fromDate, toDate, true);
  }

  async getVolatility(symbol: string, fromDate?: string, toDate?: string): Promise<any[]> {
    return this.get<any[]>("/api/v1/quant/volatility", { symbol, fromDate, toDate });
  }

  async getBeta(symbol: string, fromDate?: string, toDate?: string): Promise<any[]> {
    return this.get<any[]>("/api/v1/quant/beta", { symbol, fromDate, toDate });
  }

  async calculatePricing(params: any): Promise<any> {
    return this.post<any>("/api/quant/calculate", params);
  }

  async getWarrantAnalytics(symbol: string): Promise<any> {
    return this.get<any>(`/api/quant/${encodeURIComponent(symbol)}`);
  }
}

export const backendClient = new BackendClient();
