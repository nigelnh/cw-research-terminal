/** Compatibility helpers. Live candle ownership is backend trade-stream only. */
import type { HistoricalBar, MarketQuote } from "@/domain/models";
import type { ChartInterval } from "./types";

export function getIntervalDurationMs(interval: ChartInterval): number {
  switch (interval) {
    case "1m": return 60_000;
    case "5m": return 5 * 60_000;
    case "15m": return 15 * 60_000;
    case "30m": return 30 * 60_000;
    case "1h": return 60 * 60_000;
    case "1D": return 24 * 60 * 60_000;
    case "1W": return 7 * 24 * 60 * 60_000;
    case "1M": return 30 * 24 * 60 * 60_000;
  }
}

export function getIntervalBucketStartMs(timestampMs: number, interval: ChartInterval): number {
  const duration = getIntervalDurationMs(interval);
  return Math.floor(timestampMs / duration) * duration;
}

/**
 * Deprecated no-op retained for source compatibility. A quote carries session OHLC and
 * cumulative volume, so it can never be a legitimate interval candle input.
 */
export function mergeCompletedBarsWithLiveQuote(
  bars: HistoricalBar[],
  _quote?: MarketQuote | null,
  _interval: ChartInterval = "1D",
  _timestampMs?: number,
): HistoricalBar[] {
  return bars ?? [];
}
