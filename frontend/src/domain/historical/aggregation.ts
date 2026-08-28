/**
 * Canonical OHLCV Local Aggregation Engine (PROJECT_DESIGN)
 *
 * Implements strict mathematical coarsening of finer-grained bars into coarser intervals.
 * Invariants:
 * 1. Open = first valid trade open in interval
 * 2. High = max high across interval
 * 3. Low = min low across interval
 * 4. Close = last valid trade close in interval
 * 5. Volume = sum of trade volumes across interval
 * 6. Never average OHLC prices
 * 7. Never fabricate bars when there were no trades
 */

import type { HistoricalBar } from "@/domain/models";
import type { ChartInterval } from "./types";

/**
 * Returns ISO Year-Week string (e.g. "2026-W34") for a given date YYYY-MM-DD.
 */
export function getISOYearWeek(dateStr: string): string {
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return dateStr;

  // Set to nearest Thursday: current date + 4 - current day number (Monday=1, Sunday=7)
  const day = d.getUTCDay() || 7;
  d.setUTCDate(d.getUTCDate() + 4 - day);

  const yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
  const weekNo = Math.ceil(((d.getTime() - yearStart.getTime()) / 86400000 + 1) / 7);
  return `${d.getUTCFullYear()}-W${String(weekNo).padStart(2, "0")}`;
}

/**
 * Returns Year-Month string (e.g. "2026-08") for a given date YYYY-MM-DD.
 */
export function getYearMonth(dateStr: string): string {
  return dateStr.slice(0, 7);
}

/**
 * Parses timestamp from date string (supports YYYY-MM-DD, YYYY-MM-DD HH:mm:ss, ISO).
 */
export function parseBarTimestampMs(dateStr: string): number {
  if (!dateStr) return 0;
  // If only YYYY-MM-DD, treat as UTC date or standard date
  if (dateStr.length === 10 && dateStr.includes("-")) {
    return new Date(`${dateStr}T00:00:00Z`).getTime();
  }
  const parsed = new Date(dateStr.replace(" ", "T")).getTime();
  return isNaN(parsed) ? new Date(dateStr).getTime() : parsed;
}

/**
 * Aggregates daily OHLCV bars into weekly (1W) bars.
 */
export function aggregateDailyToWeekly(bars: HistoricalBar[]): HistoricalBar[] {
  if (!bars || bars.length === 0) return [];

  const weekGroups = new Map<string, HistoricalBar[]>();
  for (const bar of bars) {
    if (!bar.date) continue;
    const weekKey = getISOYearWeek(bar.date);
    if (!weekGroups.has(weekKey)) {
      weekGroups.set(weekKey, []);
    }
    weekGroups.get(weekKey)!.push(bar);
  }

  const weeklyBars: HistoricalBar[] = [];
  for (const [, group] of weekGroups.entries()) {
    if (group.length === 0) continue;

    // Filter valid bars with numbers
    const valid = group.filter(
      (b) => b.open !== null && b.high !== null && b.low !== null && b.close !== null
    );
    if (valid.length === 0) continue;

    // Open from first trading day of the week, Close from last trading day
    const firstBar = valid[0];
    const lastBar = valid[valid.length - 1];

    let maxHigh = -Infinity;
    let minLow = Infinity;
    let totalVol = 0;

    for (const b of valid) {
      if (b.high !== null && b.high > maxHigh) maxHigh = b.high;
      if (b.low !== null && b.low < minLow) minLow = b.low;
      if (b.volume !== null && !isNaN(b.volume)) totalVol += b.volume;
    }

    weeklyBars.push({
      symbol: firstBar.symbol,
      date: firstBar.date, // Use the week's first trading date
      open: firstBar.open,
      high: maxHigh === -Infinity ? firstBar.high : maxHigh,
      low: minLow === Infinity ? firstBar.low : minLow,
      close: lastBar.close,
      volume: totalVol,
    });
  }

  return weeklyBars;
}

/**
 * Aggregates daily OHLCV bars into monthly (1M) bars.
 */
export function aggregateDailyToMonthly(bars: HistoricalBar[]): HistoricalBar[] {
  if (!bars || bars.length === 0) return [];

  const monthGroups = new Map<string, HistoricalBar[]>();
  for (const bar of bars) {
    if (!bar.date) continue;
    const monthKey = getYearMonth(bar.date);
    if (!monthGroups.has(monthKey)) {
      monthGroups.set(monthKey, []);
    }
    monthGroups.get(monthKey)!.push(bar);
  }

  const monthlyBars: HistoricalBar[] = [];
  for (const [, group] of monthGroups.entries()) {
    if (group.length === 0) continue;

    const valid = group.filter(
      (b) => b.open !== null && b.high !== null && b.low !== null && b.close !== null
    );
    if (valid.length === 0) continue;

    const firstBar = valid[0];
    const lastBar = valid[valid.length - 1];

    let maxHigh = -Infinity;
    let minLow = Infinity;
    let totalVol = 0;

    for (const b of valid) {
      if (b.high !== null && b.high > maxHigh) maxHigh = b.high;
      if (b.low !== null && b.low < minLow) minLow = b.low;
      if (b.volume !== null && !isNaN(b.volume)) totalVol += b.volume;
    }

    monthlyBars.push({
      symbol: firstBar.symbol,
      date: firstBar.date, // First trading date of the month
      open: firstBar.open,
      high: maxHigh === -Infinity ? firstBar.high : maxHigh,
      low: minLow === Infinity ? firstBar.low : minLow,
      close: lastBar.close,
      volume: totalVol,
    });
  }

  return monthlyBars;
}

/**
 * Aggregates intraday bars (e.g. 5m) into coarser intraday intervals (e.g. 15m, 30m, 1h).
 */
export function aggregateIntradayBars(
  bars: HistoricalBar[],
  bucketMinutes: number
): HistoricalBar[] {
  if (!bars || bars.length === 0 || bucketMinutes <= 0) return bars;

  const bucketMs = bucketMinutes * 60 * 1000;
  const groups = new Map<number, HistoricalBar[]>();

  for (const b of bars) {
    const ts = parseBarTimestampMs(b.date);
    if (!ts || isNaN(ts)) continue;
    const bucketKey = Math.floor(ts / bucketMs) * bucketMs;
    if (!groups.has(bucketKey)) {
      groups.set(bucketKey, []);
    }
    groups.get(bucketKey)!.push(b);
  }

  const aggregated: HistoricalBar[] = [];
  for (const [bucketTs, group] of groups.entries()) {
    const valid = group.filter(
      (b) => b.open !== null && b.high !== null && b.low !== null && b.close !== null
    );
    if (valid.length === 0) continue;

    const firstBar = valid[0];
    const lastBar = valid[valid.length - 1];

    let maxHigh = -Infinity;
    let minLow = Infinity;
    let totalVol = 0;

    for (const b of valid) {
      if (b.high !== null && b.high > maxHigh) maxHigh = b.high;
      if (b.low !== null && b.low < minLow) minLow = b.low;
      if (b.volume !== null && !isNaN(b.volume)) totalVol += b.volume;
    }

    // Format bucket timestamp back into date string
    const dt = new Date(bucketTs);
    const dateStr = dt.toISOString().replace("T", " ").slice(0, 19);

    aggregated.push({
      symbol: firstBar.symbol,
      date: firstBar.date || dateStr,
      open: firstBar.open,
      high: maxHigh === -Infinity ? firstBar.high : maxHigh,
      low: minLow === Infinity ? firstBar.low : minLow,
      close: lastBar.close,
      volume: totalVol,
    });
  }

  return aggregated;
}

/**
 * Universal bar aggregator: coarsens a base series to a target interval if applicable.
 */
export function coarsenBarsToInterval(
  baseBars: HistoricalBar[],
  targetInterval: ChartInterval,
  sourceGranularity: string = "1D"
): HistoricalBar[] {
  if (!baseBars || baseBars.length === 0) return [];

  if (targetInterval === "1W") {
    return aggregateDailyToWeekly(baseBars);
  }

  if (targetInterval === "1M") {
    return aggregateDailyToMonthly(baseBars);
  }

  if (targetInterval === "15m" && sourceGranularity === "5m") {
    return aggregateIntradayBars(baseBars, 15);
  }

  if (targetInterval === "30m" && (sourceGranularity === "5m" || sourceGranularity === "15m")) {
    return aggregateIntradayBars(baseBars, 30);
  }

  if (targetInterval === "1h" && sourceGranularity !== "1h" && sourceGranularity !== "1D") {
    return aggregateIntradayBars(baseBars, 60);
  }

  return baseBars;
}
