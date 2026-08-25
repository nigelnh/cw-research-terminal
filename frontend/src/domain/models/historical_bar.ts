/**
 * Canonical Historical Time-Series Models
 */

export interface HistoricalBar {
  symbol: string;
  date: string; // YYYY-MM-DD
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  volume: number | null;
  referencePrice?: number | null;
  value?: number | null;
}

export interface UnderlyingClosePoint {
  symbol: string;
  date: string;
  close: number | null;
  rawClose: number | null;
}

export interface AdjustedComparisonPoint {
  symbol: string;
  date: string;
  closePrice: number | null;
  basicPrice: number | null;
  adjustedRate: number | null;
  totalAdjustedRate: number | null;
  adjustedClosePrice: number | null;
}

export interface IndexBar {
  name: string;
  date: string;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
}
