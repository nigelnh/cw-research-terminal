import type { HistoricalDataProvider, DateRange } from "@/data/providers";
import type { HistoricalBar, UnderlyingClosePoint, AdjustedComparisonPoint, IndexBar } from "@/domain/models";
import type { ChartInterval } from "@/domain/historical/types";
import { BackendClient, backendClient } from "./backend_client";
import { fetchHistoricalBars } from "@/data/query/historical_bars";

/**
 * Thin adapter over the historical endpoint. Caching / request coalescing / cancellation
 * are TanStack Query's job (see @/data/query/use_historical_bars) - this class holds no
 * state, no localStorage, no in-flight map. Kept for the HistoricalDataProvider interface
 * and the handful of derived-shape helpers.
 */
export class BackendHistoricalDataProvider implements HistoricalDataProvider {
  private client: BackendClient;

  constructor(client?: BackendClient) {
    this.client = client || backendClient;
  }

  async getHistoricalBars(
    symbol: string,
    timeframe: string = "3M",
    adjusted: boolean = true,
    _isTradingActive: boolean = false,
    interval?: string
  ): Promise<HistoricalBar[]> {
    return fetchHistoricalBars(
      { symbol, timeframe, adjusted, interval: interval as ChartInterval | undefined },
      undefined,
      this.client
    );
  }

  async getHistoricalWarrantBars(symbol: string, range: DateRange): Promise<HistoricalBar[]> {
    const days = Math.round(
      (new Date(range.toDate).getTime() - new Date(range.fromDate).getTime()) / 86400000
    );
    const tf =
      days <= 1 ? "1D" : days <= 7 ? "5D" : days <= 35 ? "1M" : days <= 100 ? "3M" : days <= 200 ? "6M" : "1Y";
    return this.getHistoricalBars(symbol, tf, true);
  }

  async getUnderlyingCloseHistory(symbol: string, range: DateRange): Promise<UnderlyingClosePoint[]> {
    const bars = await this.getHistoricalWarrantBars(symbol, range);
    return bars.map((b) => ({ symbol: b.symbol, date: b.date, close: b.close, rawClose: b.close }));
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
