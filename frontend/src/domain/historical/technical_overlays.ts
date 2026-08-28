/**
 * Technical Overlays and Normalized Relative Performance Engine
 *
 * Implements P1 overlays: EMA 20/50/200, VWAP, and Normalized Relative Performance (Base 100).
 * No indicator bloat.
 */

import type { HistoricalBar, UnderlyingClosePoint } from "@/domain/models";

export interface OverlayPoint {
  time: string; // YYYY-MM-DD or datetime
  value: number;
}

export interface RelativePoint {
  time: string;
  cw: number | null;
  underlying: number | null;
}

/**
 * Calculates Exponential Moving Average (EMA) for a given period.
 */
export function calculateEMA(bars: HistoricalBar[], period: number): OverlayPoint[] {
  if (!bars || bars.length < period || period <= 0) return [];

  const k = 2 / (period + 1);
  const result: OverlayPoint[] = [];

  // Calculate initial SMA for first `period` bars
  let sum = 0;
  let validInitialCount = 0;
  for (let i = 0; i < period; i++) {
    if (bars[i].close !== null && !isNaN(bars[i].close!)) {
      sum += bars[i].close!;
      validInitialCount++;
    }
  }

  if (validInitialCount === 0) return [];
  let prevEma = sum / validInitialCount;
  result.push({ time: bars[period - 1].date, value: prevEma });

  // Calculate subsequent EMAs
  for (let i = period; i < bars.length; i++) {
    const close = bars[i].close;
    if (close !== null && !isNaN(close)) {
      prevEma = close * k + prevEma * (1 - k);
      result.push({ time: bars[i].date, value: prevEma });
    }
  }

  return result;
}

/**
 * Calculates Volume Weighted Average Price (VWAP) for intraday sessions.
 * VWAP = cumulative(Typical Price * Volume) / cumulative(Volume)
 * Typical Price = (High + Low + Close) / 3
 */
export function calculateVWAP(bars: HistoricalBar[]): OverlayPoint[] {
  if (!bars || bars.length === 0) return [];

  let cumVolume = 0;
  let cumTypicalVol = 0;
  const result: OverlayPoint[] = [];

  for (const b of bars) {
    if (
      b.high !== null &&
      b.low !== null &&
      b.close !== null &&
      b.volume !== null &&
      b.volume > 0 &&
      !isNaN(b.high) &&
      !isNaN(b.low) &&
      !isNaN(b.close) &&
      !isNaN(b.volume)
    ) {
      const typicalPrice = (b.high + b.low + b.close) / 3;
      cumTypicalVol += typicalPrice * b.volume;
      cumVolume += b.volume;

      if (cumVolume > 0) {
        result.push({
          time: b.date,
          value: cumTypicalVol / cumVolume,
        });
      }
    }
  }

  return result;
}

/**
 * Normalizes both CW and Underlying series to a common baseline of 100.0.
 * Allows direct visual inspection of leverage and relative performance.
 */
export function calculateNormalizedRelative(
  cwBars: HistoricalBar[],
  undBars: (HistoricalBar | UnderlyingClosePoint)[]
): RelativePoint[] {
  const validCw = (cwBars || []).filter((b) => b.close !== null && !isNaN(b.close!));
  const validUnd = (undBars || []).filter((b) => b.close !== null && !isNaN(b.close!));

  if (validUnd.length === 0 && validCw.length === 0) return [];

  // Map dates to close values
  const cwMap = new Map<string, number>();
  for (const b of validCw) {
    if (b.date && b.close !== null) cwMap.set(b.date, b.close);
  }

  const undMap = new Map<string, number>();
  for (const b of validUnd) {
    if (b.date && b.close !== null) undMap.set(b.date, b.close);
  }

  // Collect all unique sorted dates
  const allDates = Array.from(new Set([...cwMap.keys(), ...undMap.keys()])).sort();
  if (allDates.length === 0) return [];

  // Find baseline values (first valid price in the series)
  const baseCw = validCw.length > 0 ? validCw[0].close! : null;
  const baseUnd = validUnd.length > 0 ? validUnd[0].close! : null;

  return allDates.map((date) => {
    const cwPrice = cwMap.get(date);
    const undPrice = undMap.get(date);

    const normCw = cwPrice !== undefined && baseCw ? (cwPrice / baseCw) * 100 : null;
    const normUnd = undPrice !== undefined && baseUnd ? (undPrice / baseUnd) * 100 : null;

    return {
      time: date,
      cw: normCw,
      underlying: normUnd,
    };
  });
}
