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

  // Seed only from a complete period. Missing prices remain gaps.
  const seed = bars.slice(0, period).map((bar) => bar.close);
  if (seed.some((close) => close === null || !Number.isFinite(close))) return [];
  let prevEma = (seed as number[]).reduce((sum, close) => sum + close, 0) / period;
  result.push({ time: bars[period - 1].date, value: prevEma });

  // Calculate subsequent EMAs
  for (let i = period; i < bars.length; i++) {
    const close = bars[i].close;
    if (close !== null && Number.isFinite(close)) {
      prevEma = close * k + prevEma * (1 - k);
      result.push({ time: bars[i].date, value: prevEma });
    } else break;
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
  let activeSession = "";
  const result: OverlayPoint[] = [];

  for (const b of bars) {
    const isIntraday = b.date.length > 10;
    const session = b.sessionDate || b.date.slice(0, 10);
    if (isIntraday && session !== activeSession) {
      activeSession = session;
      cumVolume = 0;
      cumTypicalVol = 0;
    }
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

  // A valid relative series needs a shared timestamp baseline. Non-overlapping
  // observations stay gaps and are never rebased independently.
  const allDates = Array.from(new Set([...cwMap.keys(), ...undMap.keys()])).sort();
  const baselineDate = allDates.find((d) => cwMap.has(d) && undMap.has(d));
  if (!baselineDate) return [];
  const baseCw = cwMap.get(baselineDate)!;
  const baseUnd = undMap.get(baselineDate)!;

  return allDates.map((date) => {
    const cwPrice = cwMap.get(date);
    const undPrice = undMap.get(date);

    const beforeBaseline = date < baselineDate;
    const normCw = !beforeBaseline && cwPrice !== undefined && baseCw ? (cwPrice / baseCw) * 100 : null;
    const normUnd = !beforeBaseline && undPrice !== undefined && baseUnd ? (undPrice / baseUnd) * 100 : null;

    return {
      time: date,
      cw: normCw,
      underlying: normUnd,
    };
  });
}
