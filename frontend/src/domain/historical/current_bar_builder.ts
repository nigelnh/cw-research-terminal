/**
 * Current Bar Builder (PROJECT_DESIGN)
 *
 * Incrementally merges completed historical bars with live realtime trade events
 * to construct and update the active in-flight candle.
 *
 * Invariants:
 * 1. Zero fabrication: Bid/Ask without trades NEVER generates a candle.
 * 2. If quote.lastPrice is null, no current trade candle is created.
 * 3. High/Low expand dynamically as live trades arrive.
 * 4. Interval boundaries cleanly transition when clock ticks past interval end.
 */

import type { HistoricalBar, MarketQuote } from "@/domain/models";
import type { ChartInterval } from "./types";
import { parseBarTimestampMs } from "./aggregation";

export interface CurrentBarState {
  bars: HistoricalBar[];
  activeLiveBar: HistoricalBar | null;
}

/**
 * Returns interval duration in milliseconds for an interval string.
 */
export function getIntervalDurationMs(interval: ChartInterval): number {
  switch (interval) {
    case "1m":
      return 60 * 1000;
    case "5m":
      return 5 * 60 * 1000;
    case "15m":
      return 15 * 60 * 1000;
    case "30m":
      return 30 * 60 * 1000;
    case "1h":
      return 60 * 60 * 1000;
    case "1D":
      return 24 * 60 * 60 * 1000;
    case "1W":
      return 7 * 24 * 60 * 60 * 1000;
    case "1M":
      return 30 * 24 * 60 * 60 * 1000;
    default:
      return 24 * 60 * 60 * 1000;
  }
}

/**
 * Calculates current interval bucket start timestamp.
 */
export function getIntervalBucketStartMs(timestampMs: number, interval: ChartInterval): number {
  const duration = getIntervalDurationMs(interval);
  return Math.floor(timestampMs / duration) * duration;
}

/**
 * Merges historical completed bars with current realtime quote.
 */
export function mergeCompletedBarsWithLiveQuote(
  bars: HistoricalBar[],
  quote?: MarketQuote | null,
  interval: ChartInterval = "1D",
  nowMs: number = Date.now()
): HistoricalBar[] {
  if (!bars || bars.length === 0) {
    // If no historical bars, check if quote has a valid matched trade
    if (quote && quote.lastPrice !== null && !isNaN(quote.lastPrice)) {
      const dateStr = new Date(nowMs).toISOString().split("T")[0];
      return [
        {
          symbol: quote.symbol,
          date: dateStr,
          open: quote.openPrice ?? quote.lastPrice,
          high: quote.highPrice ?? quote.lastPrice,
          low: quote.lowPrice ?? quote.lastPrice,
          close: quote.lastPrice,
          volume: quote.totalVolume ?? 0,
        },
      ];
    }
    return [];
  }

  // If no quote or no matched trade price in quote, return completed bars as-is
  if (!quote || quote.lastPrice === null || isNaN(quote.lastPrice)) {
    return bars;
  }

  const result = [...bars];
  const lastIndex = result.length - 1;
  const lastBar = result[lastIndex];
  const lastBarTs = parseBarTimestampMs(lastBar.date);

  const currentBucketStart = getIntervalBucketStartMs(nowMs, interval);
  const lastBarBucketStart = getIntervalBucketStartMs(lastBarTs, interval);

  const livePrice = quote.lastPrice;

  // If latest bar falls in the current interval bucket, update it
  if (lastBarBucketStart === currentBucketStart || (interval === "1D" && lastBar.date.startsWith(new Date(nowMs).toISOString().split("T")[0]))) {
    result[lastIndex] = {
      ...lastBar,
      open: lastBar.open ?? quote.openPrice ?? livePrice,
      high: Math.max(lastBar.high ?? livePrice, quote.highPrice ?? livePrice, livePrice),
      low: Math.min(lastBar.low ?? livePrice, quote.lowPrice ?? livePrice, livePrice),
      close: livePrice,
      volume: quote.totalVolume ?? lastBar.volume ?? 0,
    };
  } else if (currentBucketStart > lastBarBucketStart) {
    // New interval has started, append fresh live candle
    const dateStr = interval === "1D" || interval === "1W" || interval === "1M"
      ? new Date(nowMs).toISOString().split("T")[0]
      : new Date(currentBucketStart).toISOString().replace("T", " ").slice(0, 19);

    result.push({
      symbol: quote.symbol,
      date: dateStr,
      open: quote.openPrice ?? livePrice,
      high: quote.highPrice ?? livePrice,
      low: quote.lowPrice ?? livePrice,
      close: livePrice,
      volume: quote.totalVolume ?? 0,
    });
  }

  return result;
}
