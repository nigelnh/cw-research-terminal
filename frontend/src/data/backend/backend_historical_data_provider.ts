import type { HistoricalDataProvider, DateRange } from "@/data/providers";
import type { HistoricalBar, UnderlyingClosePoint, AdjustedComparisonPoint, IndexBar } from "@/domain/models";
import { BackendClient, backendClient } from "./backend_client";
import { mapRawCWDataToHistoricalBar } from "./mappers";
import {
  HistoricalDataCache,
  type HistoricalDataset,
  type HistoricalBarRow,
} from "@/data/historical/historical_data_cache";
import { coarsenBarsToInterval } from "@/domain/historical/aggregation";

export class BackendHistoricalDataProvider implements HistoricalDataProvider {
  private client: BackendClient;
  private inFlightRequests: Map<string, Promise<HistoricalBar[]>> = new Map();

  constructor(client?: BackendClient) {
    this.client = client || backendClient;
  }

  /**
   * Slices historical daily/intraday bars client-side based on requested timeframe/range.
   */
  private sliceBars(bars: HistoricalBar[], timeframe: string): HistoricalBar[] {
    if (!bars || bars.length === 0) return [];
    const tf = timeframe.toUpperCase();

    if (tf === "1M") {
      // Last 30 calendar days
      const cutoff = new Date(Date.now() - 30 * 86400000).toISOString().split("T")[0];
      const filtered = bars.filter((b) => b.date >= cutoff);
      return filtered.length > 0 ? filtered : bars.slice(-22);
    }

    if (tf === "3M") {
      // Last 90 calendar days
      const cutoff = new Date(Date.now() - 90 * 86400000).toISOString().split("T")[0];
      const filtered = bars.filter((b) => b.date >= cutoff);
      return filtered.length > 0 ? filtered : bars.slice(-66);
    }

    if (tf === "6M") {
      // Last 180 calendar days
      const cutoff = new Date(Date.now() - 180 * 86400000).toISOString().split("T")[0];
      const filtered = bars.filter((b) => b.date >= cutoff);
      return filtered.length > 0 ? filtered : bars.slice(-130);
    }

    if (tf === "1Y" || tf === "MAX" || tf === "ALL") {
      return bars;
    }

    if (tf === "1D") {
      return bars;
    }

    if (tf === "5D") {
      return bars;
    }

    return bars;
  }

  /**
   * Retrieves historical bars for a symbol with timeframe-aware dataset selection, local aggregation, and caching.
   * Dataset mappings:
   * - "1D" -> "intraday_1d" (5m granularity)
   * - "5D" -> "intraday_5d" (30m granularity)
   * - "1M", "3M", "6M", "1Y", "MAX" -> "daily_1y" (1d granularity, sliced and aggregated client-side)
   */
  async getHistoricalBars(
    symbol: string,
    timeframe: string = "3M",
    adjusted: boolean = true,
    isTradingActive: boolean = false,
    interval?: string
  ): Promise<HistoricalBar[]> {
    const sym = symbol.trim().toUpperCase();
    const tf = timeframe.toUpperCase();

    // Map timeframe to canonical dataset class
    let dataset: HistoricalDataset = "daily_1y";
    let backendTf = "1D";

    if (tf === "1D") {
      dataset = "intraday_1d";
      backendTf = "5m";
    } else if (tf === "5D") {
      dataset = "intraday_5d";
      backendTf = "30m";
    } else {
      dataset = "daily_1y";
      backendTf = "1D";
    }

    const targetInterval = (interval || (tf === "1D" ? "5m" : (tf === "5D" ? "30m" : "1D"))) as any;

    // 1. Check LocalStorage Cache
    const cached = HistoricalDataCache.get(sym, dataset);
    if (cached && HistoricalDataCache.isFresh(cached, isTradingActive)) {
      const mappedCached: HistoricalBar[] = cached.rows.map((r) => ({
        symbol: sym,
        date: r.date,
        open: r.open,
        high: r.high,
        low: r.low,
        close: r.close,
        volume: r.volume,
      }));
      const sliced = this.sliceBars(mappedCached, tf);
      return coarsenBarsToInterval(sliced, targetInterval, backendTf);
    }

    // 2. Coalesce in-flight simultaneous requests for same (symbol, dataset)
    const requestKey = `${sym}:${dataset}`;
    if (this.inFlightRequests.has(requestKey)) {
      const pendingBars = await this.inFlightRequests.get(requestKey)!;
      const sliced = this.sliceBars(pendingBars, tf);
      return coarsenBarsToInterval(sliced, targetInterval, backendTf);
    }

    // 3. Fetch from backend
    const fetchPromise = (async (): Promise<HistoricalBar[]> => {
      try {
        const raw = await this.client.getMarketHistory(sym, backendTf, undefined, undefined, adjusted);
        const mapped = (raw || []).map(mapRawCWDataToHistoricalBar);

        if (mapped.length > 0) {
          const rowsToCache: HistoricalBarRow[] = mapped.map((b) => ({
            date: b.date,
            open: b.open,
            high: b.high,
            low: b.low,
            close: b.close,
            volume: b.volume,
            adjusted,
          }));
          HistoricalDataCache.set(sym, dataset, rowsToCache, backendTf, adjusted);
        }
        return mapped;
      } catch (err: any) {
        // Rate limit or network fallback: if cached data exists (even if stale), return it
        if (cached && cached.rows.length > 0) {
          return cached.rows.map((r) => ({
            symbol: sym,
            date: r.date,
            open: r.open,
            high: r.high,
            low: r.low,
            close: r.close,
            volume: r.volume,
          }));
        }
        throw err;
      } finally {
        this.inFlightRequests.delete(requestKey);
      }
    })();

    this.inFlightRequests.set(requestKey, fetchPromise);
    const fetchedBars = await fetchPromise;
    const sliced = this.sliceBars(fetchedBars, tf);
    return coarsenBarsToInterval(sliced, targetInterval, backendTf);
  }

  async getHistoricalWarrantBars(symbol: string, range: DateRange): Promise<HistoricalBar[]> {
    // Map DateRange to timeframe if possible
    const days = Math.round(
      (new Date(range.toDate).getTime() - new Date(range.fromDate).getTime()) / 86400000
    );
    let tf = "3M";
    if (days <= 1) tf = "1D";
    else if (days <= 7) tf = "5D";
    else if (days <= 35) tf = "1M";
    else if (days <= 100) tf = "3M";
    else if (days <= 200) tf = "6M";
    else tf = "1Y";

    return this.getHistoricalBars(symbol, tf, true);
  }

  async getUnderlyingCloseHistory(symbol: string, range: DateRange): Promise<UnderlyingClosePoint[]> {
    const bars = await this.getHistoricalWarrantBars(symbol, range);
    return bars.map((b) => ({
      symbol: b.symbol,
      date: b.date,
      close: b.close,
      rawClose: b.close,
    }));
  }

  async getAdjustedUnderlyingComparison(stockCode: string, range: DateRange): Promise<AdjustedComparisonPoint[]> {
    const bars = await this.getHistoricalWarrantBars(stockCode, range);
    return bars.map((b) => ({
      symbol: b.symbol,
      date: b.date,
      closePrice: b.close,
      basicPrice: b.open,
      adjustedRate: null,
      totalAdjustedRate: null,
      adjustedClosePrice: b.close,
    }));
  }

  async getIndexHistory(name: string, range: DateRange): Promise<IndexBar[]> {
    const bars = await this.getHistoricalWarrantBars(name, range);
    return bars.map((b) => ({
      name: b.symbol || name,
      date: b.date,
      open: b.open,
      high: b.high,
      low: b.low,
      close: b.close,
    }));
  }
}

export const backendHistoricalDataProvider = new BackendHistoricalDataProvider();
