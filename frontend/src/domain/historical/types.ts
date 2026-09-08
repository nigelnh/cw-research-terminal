/**
 * Canonical Historical Time-Series and Chart Types
 */

export type ChartRange = "1D" | "5D" | "1M" | "3M" | "6M" | "1Y" | "MAX";
export type ChartInterval = "1m" | "5m" | "15m" | "30m" | "1h" | "1D" | "1W" | "1M";
export type CWHistoryMode = "CW" | "UNDERLYING" | "BOTH" | "RELATIVE";
export type TechnicalOverlay = "REF" | "EMA20" | "EMA50" | "EMA200" | "VWAP";

/**
 * Project-owned Range to Compatible Intervals mapping (PROJECT_DESIGN).
 * Enforces sensible resolution bounds to prevent absurd combinations or rate-limit pressure.
 */
export const RANGE_INTERVAL_COMPATIBILITY: Record<ChartRange, ChartInterval[]> = {
  "1D": ["1m", "5m", "15m"],
  "5D": ["5m", "15m", "30m", "1h"],
  "1M": ["15m", "30m", "1h", "1D"],
  "3M": ["1h", "1D"],
  "6M": ["1D", "1W"],
  "1Y": ["1D", "1W", "1M"],
  "MAX": ["1D", "1W", "1M"],
};

/**
 * Sensible default interval when switching to a new Range.
 */
export const DEFAULT_INTERVAL_FOR_RANGE: Record<ChartRange, ChartInterval> = {
  "1D": "5m",
  "5D": "15m",
  "1M": "1D",
  "3M": "1D",
  "6M": "1D",
  "1Y": "1D",
  "MAX": "1W",
};

/**
 * Vendor-Native Intervals (DOCS_CONFIRMED by FiinQuant):
 * 1m, 5m, 15m, 30m, 1h, 1d
 *
 * Project-Derived Intervals (PROJECT_DESIGN):
 * 1W, 1M (Aggregated from daily bars)
 */
export const VENDOR_NATIVE_INTERVALS: ReadonlySet<string> = new Set([
  "1m",
  "5m",
  "15m",
  "30m",
  "1h",
  "1d",
  "1D",
]);

export interface OHLCVReadout {
  source?: string | null;
  sessionDate?: string | null;
  priceBasis?: string | null;
  asOf?: string | null;
  complete?: boolean;
  symbol: string;
  interval: ChartInterval;
  timestamp: string; // ISO or date string
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  volume: number | null;
  change: number | null;
  changePercent: number | null;
  isLive?: boolean;
}
