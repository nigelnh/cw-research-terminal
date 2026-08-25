import { config } from "@/config";

export class BackendClient {
  private baseUrl: string;

  constructor(baseUrl?: string) {
    this.baseUrl = (baseUrl || config.apiUrl || "http://localhost:8000").replace(/\/$/, "");
  }

  private async get<T>(path: string, params?: Record<string, string | number | undefined>): Promise<T> {
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
  async getActiveInstruments(issuer?: string, underlying?: string, search?: string): Promise<any[]> {
    try {
      const res = await this.get<{ total: number; active_count: number; items: any[] }>("/api/instruments", {
        issuer,
        underlying,
        search,
        active_only: "true",
      });
      return res.items || [];
    } catch (err) {
      console.warn("[BackendClient] Failed to fetch /api/instruments:", err);
      throw err;
    }
  }

  async getInstrumentSpecification(symbol: string): Promise<any> {
    return this.get<any>(`/api/instruments/${encodeURIComponent(symbol.toUpperCase())}`);
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

  async getHistoricalCWData(symbol?: string, fromDate?: string, toDate?: string): Promise<any[]> {
    return this.get<any[]>("/api/cw/data", { symbol, fromDate, toDate });
  }

  async getComparison(stockCode: string, fromDate?: string, toDate?: string): Promise<any[]> {
    return this.get<any[]>("/api/cw/comparison", { stockcode: stockCode, fromDate, toDate });
  }

  async getStockCloseHistory(symbol: string, fromDate?: string, toDate?: string): Promise<any[]> {
    return this.get<any[]>("/api/v1/history/stocks/close", { symbol, fromDate, toDate });
  }

  async getIndexHistory(name: string = "VNINDEX", fromDate?: string, toDate?: string): Promise<any[]> {
    return this.get<any[]>("/api/v1/history/index", { name, fromDate, toDate });
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
