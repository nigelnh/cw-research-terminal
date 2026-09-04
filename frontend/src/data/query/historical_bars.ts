/**
 * Pure fetch + shaping logic for historical bars. No caching, no in-flight coalescing -
 * TanStack Query owns both. This is the domain logic that used to live inside
 * BackendHistoricalDataProvider.getHistoricalBars().
 */

import type { HistoricalBar } from "@/domain/models";
import type { ChartInterval } from "@/domain/historical/types";
import { coarsenBarsToInterval } from "@/domain/historical/aggregation";
import { mapRawCWDataToHistoricalBar } from "@/data/backend/mappers";
import { backendClient, type BackendClient } from "@/data/backend/backend_client";

export type HistoricalDataset = "intraday_1d" | "intraday_5d" | "daily_1y";

export interface HistoricalBarsRequest {
  symbol: string;
  /** UI timeframe token: 1D | 5D | 1M | 3M | 6M | 1Y | MAX (also ALL) */
  timeframe: string;
  adjusted: boolean;
  /** resolution the chart renders at */
  interval?: ChartInterval | string;
}

/** UI timeframe -> canonical dataset class + the backend `timeframe` query param. */
export function resolveDataset(timeframe: string): {
  dataset: HistoricalDataset;
  backendTimeframe: string;
} {
  const tf = timeframe.toUpperCase();
  if (tf === "1D") return { dataset: "intraday_1d", backendTimeframe: "5m" };
  if (tf === "5D") return { dataset: "intraday_5d", backendTimeframe: "30m" };
  return { dataset: "daily_1y", backendTimeframe: "1D" };
}

/** Client-side slice of a full dataset to the requested UI timeframe. */
export function sliceBars(bars: HistoricalBar[], timeframe: string): HistoricalBar[] {
  if (!bars || bars.length === 0) return [];
  const tf = timeframe.toUpperCase();
  const latest = bars.reduce((max, bar) => bar.date > max ? bar.date : max, "").slice(0, 10);

  const sliceByDays = (days: number, minTail: number): HistoricalBar[] => {
    const anchor = new Date(`${latest}T00:00:00+07:00`).getTime();
    const cutoff = new Date(anchor - days * 86400000).toLocaleDateString("sv-SE", { timeZone: "Asia/Ho_Chi_Minh" });
    const filtered = bars.filter((b) => b.date >= cutoff);
    return filtered.length > 0 ? filtered : bars.slice(-minTail);
  };

  if (tf === "1M") return sliceByDays(30, 22);
  if (tf === "3M") return sliceByDays(90, 66);
  if (tf === "6M") return sliceByDays(180, 130);
  if (tf === "1D") return bars.filter((bar) => bar.date.slice(0, 10) === latest);
  if (tf === "5D") return sliceByDays(7, 5 * 48);
  // 1Y, MAX, ALL -> whole returned dataset
  return bars;
}

/**
 * Fetch + shape historical bars for one (symbol, timeframe, interval, adjusted) request.
 * ``signal`` is threaded from TanStack Query for cancellation of superseded requests.
 */
export async function fetchHistoricalBars(
  req: HistoricalBarsRequest,
  signal?: AbortSignal,
  client: BackendClient = backendClient
): Promise<HistoricalBar[]> {
  const sym = req.symbol.trim().toUpperCase();
  const { backendTimeframe } = resolveDataset(req.timeframe);
  const targetInterval = (req.interval ||
    (req.timeframe.toUpperCase() === "1D" ? "5m" : req.timeframe.toUpperCase() === "5D" ? "30m" : "1D")) as ChartInterval;

  const raw = await client.getMarketHistory(sym, backendTimeframe, undefined, undefined, req.adjusted, signal);
  const mapped = (raw || []).map(mapRawCWDataToHistoricalBar);
  const sliced = sliceBars(mapped, req.timeframe);
  return coarsenBarsToInterval(sliced, targetInterval, backendTimeframe);
}
