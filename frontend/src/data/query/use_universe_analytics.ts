import { useMemo } from "react";
import { useDashboardData } from "./use_dashboard_data";
import { useInstrumentSpecs } from "@/data/instruments/use_instrument_specs";

/**
 * Cross-sectional analytics for a set of symbols, shaped for charting.
 *
 * This is a SELECTOR, not a new fetch: it reads `useDashboardData` (quotes +
 * `/api/market/dashboard/analytics`) and `useInstrumentSpecs` (the contract registry) and
 * joins them. Both are React Query caches the Dashboard already populates for the same
 * watchlist, so opening Research costs zero extra network — and the 60-symbol cap on the
 * analytics endpoint comfortably covers a 30-symbol watchlist in one call.
 *
 * Only CW rows with `isAvailable` analytics become points; stocks and indices in the
 * watchlist have no strike, so no moneyness and no implied vol.
 */
export interface UniversePoint {
  symbol: string;
  underlying: string | null;
  issuer: string | null;
  /** S / K. */
  moneyness: number | null;
  /** Decimal, e.g. 0.4481 = 44.81%. */
  ivMid: number | null;
  /** Underlying's realized vol (HV22), decimal. */
  hv: number | null;
  /** (ivMid - hv) in percentage POINTS. Positive = priced richer than realized. */
  spreadPp: number | null;
  dte: number | null;
  moneynessCategory: string | null;
  /** "YYYY-MM" of the maturity date. */
  maturityMonth: string | null;
  maturityDate: string | null;
  tradingValue: number | null;
}

export interface UniverseAnalyticsResult {
  points: UniversePoint[];
  /** Distinct underlyings present in `points`, sorted — the chart series order. */
  underlyings: string[];
  /** CWs in the requested set, whether or not analytics resolved. */
  cwCount: number;
  isLoading: boolean;
  isError: boolean;
  asOf: string | null;
  /** LIVE while the session is open, otherwise the last completed session's close. */
  basis: "LIVE" | "LAST_SESSION";
}

const num = (v: unknown): number | null =>
  typeof v === "number" && Number.isFinite(v) ? v : null;

export function useUniverseAnalytics(symbols: string[]): UniverseAnalyticsResult {
  const { getRow, meta, isLoading, isError } = useDashboardData(symbols);
  const { getSpec } = useInstrumentSpecs();

  const points: UniversePoint[] = [];
  let cwCount = 0;
  for (const symbol of symbols) {
    const spec = getSpec(symbol);
    if (spec && spec.instrumentType !== "CW") continue;
    const row = getRow(symbol);
    const a = row?.analytics;
    // A CW is only counted once the registry confirms it — an unknown symbol with no spec
    // and no analytics is not silently treated as a warrant with missing data.
    if (spec?.instrumentType === "CW") cwCount += 1;
    if (!a || a.isAvailable !== true) continue;

    const ivMid = num(a.ivMid) ?? num(a.ivTrade);
    const hv = num(a.historicalVolatility);
    const maturityDate = spec?.maturityDate ?? null;
    points.push({
      symbol: symbol.toUpperCase(),
      underlying: spec?.underlyingSymbol ?? null,
      issuer: spec?.issuer ?? null,
      moneyness: num(a.moneynessRatio),
      ivMid,
      hv,
      spreadPp: ivMid != null && hv != null ? (ivMid - hv) * 100 : null,
      dte: num(a.dte),
      moneynessCategory: typeof a.moneynessCategory === "string" ? a.moneynessCategory : null,
      maturityMonth: maturityDate ? maturityDate.slice(0, 7) : null,
      maturityDate,
      tradingValue: num(row?.quote?.tradingValue),
    });
  }
  points.sort((x, y) => x.symbol.localeCompare(y.symbol));

  const underlyings = [...new Set(points.map(p => p.underlying).filter((u): u is string => !!u))].sort();

  // Identity is stabilised on the values the charts actually read, so a WS price tick that
  // changes nothing on these axes does not hand chart.js a new dataset every second. The
  // charts therefore move on the analytics refetch cadence (30s in-session), which is the
  // right rate for a cross-sectional view.
  const signature = points
    .map(p => `${p.symbol}|${p.moneyness}|${p.ivMid}|${p.hv}|${p.dte}|${p.maturityMonth}|${p.tradingValue}`)
    .join(";");

  // eslint-disable-next-line react-hooks/exhaustive-deps
  const stablePoints = useMemo(() => points, [signature]);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const stableUnderlyings = useMemo(() => underlyings, [underlyings.join(",")]);

  return {
    points: stablePoints,
    underlyings: stableUnderlyings,
    cwCount,
    isLoading,
    isError,
    asOf: meta.asOf,
    basis: meta.marketSessionActive ? "LIVE" : "LAST_SESSION",
  };
}
