/**
 * The instrument chart's candle intervals: what each one fetches, and how day-or-longer
 * candles are built from the daily series.
 *
 * Intraday candles come straight from the source (KBS): about five months for a stock, and
 * only the current session for a covered warrant - KBS serves nothing earlier for warrants.
 * Every day-or-longer candle is built here from ONE deep daily series (about ten years for
 * a stock, a warrant's whole life), so switching 1D -> 1W -> 1Y never refetches.
 */

import type { HistoricalBar } from "@/domain/models";
import { getISOYearWeek, getYearMonth } from "./aggregation";
import { aggregateProvenance } from "./merge_bars";
import type { ChartInterval } from "./types";

export const INTRADAY_INTERVALS = ["1m", "5m", "30m", "1h"] as const;
export const DAY_INTERVALS = ["1D", "5D", "1W", "3W", "1M", "3M", "6M", "1Y"] as const;

export type IntradayInterval = (typeof INTRADAY_INTERVALS)[number];
export type DayInterval = (typeof DAY_INTERVALS)[number];
export type InstrumentChartInterval = IntradayInterval | DayInterval;

export function isIntradayInterval(interval: string): interval is IntradayInterval {
  return (INTRADAY_INTERVALS as readonly string[]).includes(interval);
}

/**
 * The history request behind an interval. Intraday asks the source for that granularity
 * over a window sized to it; every day interval shares the one deep daily request.
 */
export function historyRequestFor(interval: InstrumentChartInterval): { timeframe: string; interval: ChartInterval } {
  if (isIntradayInterval(interval)) {
    const window: Record<IntradayInterval, string> = { "1m": "5D", "5m": "1M", "30m": "3M", "1h": "6M" };
    return { timeframe: window[interval], interval };
  }
  return { timeframe: "MAX", interval: "1D" };
}

const DAY_MS = 86_400_000;
/** A Monday, so three-week buckets always start on a Monday. */
const EPOCH_MONDAY = Date.UTC(1970, 0, 5);

function calendarKey(interval: DayInterval, date: string): string {
  const y = date.slice(0, 4);
  const m = Number(date.slice(5, 7));
  switch (interval) {
    case "1W":
      return getISOYearWeek(date);
    case "3W": {
      const days = (Date.UTC(Number(y), m - 1, Number(date.slice(8, 10))) - EPOCH_MONDAY) / DAY_MS;
      return `3W-${Math.floor(days / 21)}`;
    }
    case "1M":
      return getYearMonth(date);
    case "3M":
      return `${y}-Q${Math.floor((m - 1) / 3) + 1}`;
    case "6M":
      return `${y}-H${m <= 6 ? 1 : 2}`;
    case "1Y":
      return y;
    default:
      return date.slice(0, 10);
  }
}

function combine(group: HistoricalBar[]): HistoricalBar {
  const first = group[0];
  const last = group[group.length - 1];
  let high = -Infinity;
  let low = Infinity;
  let volume = 0;
  for (const b of group) {
    if (b.high !== null && b.high > high) high = b.high;
    if (b.low !== null && b.low < low) low = b.low;
    if (b.volume !== null && !Number.isNaN(b.volume)) volume += b.volume;
  }
  return {
    symbol: first.symbol,
    date: first.date, // a candle is dated by its first session
    open: first.open,
    high: high === -Infinity ? first.high : high,
    low: low === Infinity ? first.low : low,
    close: last.close,
    volume: group.every((b) => b.volume != null) ? volume : null,
    ...aggregateProvenance(group),
  };
}

/**
 * Daily bars -> candles of `interval`. Calendar intervals group by week / month / quarter /
 * half / year. 5D groups every five sessions, counted from the oldest bar, so it is not a
 * calendar week: holidays never shorten it.
 */
export function aggregateDaily(bars: HistoricalBar[], interval: DayInterval): HistoricalBar[] {
  const valid = bars
    .filter((b) => b.date && b.open !== null && b.high !== null && b.low !== null && b.close !== null)
    .sort((a, b) => a.date.localeCompare(b.date));
  if (interval === "1D") return valid;

  const groups: HistoricalBar[][] = [];
  if (interval === "5D") {
    for (let i = 0; i < valid.length; i += 5) groups.push(valid.slice(i, i + 5));
  } else {
    let key: string | null = null;
    for (const bar of valid) {
      const k = calendarKey(interval, bar.date);
      if (k !== key) {
        groups.push([]);
        key = k;
      }
      groups[groups.length - 1].push(bar);
    }
  }
  return groups.map(combine);
}
