import { acceptMarketContext, useMarketContext, marketNow } from "@/data/market_session_store";
import { resolveDashboardAnalytics } from "./resolve_dashboard_analytics";
import { useCallback, useEffect, useMemo, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { CoveredWarrant, MarketQuote } from "@/domain/models";
import {
  type DisplayState,
  type RowProvenance,
} from "@/domain/temporal";
import { backendClient } from "@/data/backend/backend_client";
import { mapRawSnapshotToQuote } from "@/data/backend/mappers/map_snapshot";
import { useResearchMarket } from "@/data/use_research_market";
import { resolveDashboardQuote } from "./resolve_dashboard_quote";
export { isQuoteTimestampEligible } from "./resolve_dashboard_quote";

export interface DashboardRow {
  symbol: string;
  quote: MarketQuote;
  provenance: RowProvenance;
  displayState: DisplayState;
  /** Analytics group (CW): iv/greeks/moneyness/dte, already in canonical units. */
  analytics: Record<string, any> | null;
  /** true when this symbol currently has a realtime subscription slot on the server. */
  trackedRealtime: boolean;
}

export interface DashboardMeta {
  asOf: string | null;
  marketSession: string;
  marketSessionActive: boolean;
  latestCompletedSession: string | null;
  calendarConfidence: string | null;
}

interface UseDashboardDataResult {
  getRow: (symbol: string) => DashboardRow | undefined;
  meta: DashboardMeta;
  isLoading: boolean;
  isError: boolean;
  refetch: () => unknown;
}

const EMPTY_META: DashboardMeta = {
  asOf: null,
  marketSession: "UNKNOWN",
  marketSessionActive: false,
  latestCompletedSession: null,
  calendarConfidence: null,
};

/**
 * Merges the ONE canonical realtime store (WS) with the server-side after-hours fallback
 * (`GET /api/market/dashboard`). Precedence per symbol:
 *   - active session + a fresh live WS quote  -> LIVE values
 *   - otherwise                                -> the resolved fallback row (LAST_SESSION /
 *                                                 HISTORICAL / UNAVAILABLE) with provenance
 * The WS client stays the single live owner; this hook only fills where live is absent, so
 * there is no duplicate state and no flicker to stale on the closed->open transition (the
 * query refetches when `marketSessionActive` flips).
 */
export function useDashboardData(symbols: string[]): UseDashboardDataResult {
  const { quotes, warrants, marketSessionActive, marketPhase, isRealtimeTracked } = useResearchMarket();
  const { sessionContext } = useMarketContext();
  const qc = useQueryClient();

  const sortedKey = [...new Set(symbols.map((s) => s.toUpperCase()))].sort();
  const query = useQuery({
    queryKey: ["dashboard-rows", sortedKey, sessionContext?.displaySessionDate],
    enabled: sortedKey.length > 0,
    queryFn: async ({ signal }) => { const data = await backendClient.getDashboardRows(sortedKey, signal); acceptMarketContext(data); return data; },
    staleTime: 30_000,
    refetchInterval: marketSessionActive ? 30_000 : 5 * 60_000,
    // Rows the WebSocket does not carry (anything resolved SESSION_SNAPSHOT - most thin
    // CWs) come only from this poll. React Query suspends `refetchInterval` for a hidden
    // document by default and this app also disables refetch-on-focus globally, so a
    // backgrounded tab froze those rows AND did not refresh on return: the board sat
    // visibly behind other terminals until the next tick, then jumped all at once.
    refetchIntervalInBackground: true,
    refetchOnWindowFocus: true,
  });
  const analyticsQuery = useQuery({
    queryKey: ["dashboard-analytics", sortedKey, sessionContext?.displaySessionDate],
    enabled: sortedKey.length > 0,
    queryFn: async ({ signal }) => { const data = await backendClient.getDashboardAnalytics(sortedKey, signal); acceptMarketContext(data); return data; },
    refetchInterval: 30_000,
    // Live analytics arrive over WS. This read is the independently hydrated EOD/current
    // cache and may finish later without delaying the quote table.
    staleTime: marketSessionActive ? 30_000 : 5 * 60_000,
    refetchOnWindowFocus: true,
  });

  // Refetch immediately when the session transitions (closed -> open must not keep showing
  // last-session, open -> closed must fill the fallback).
  useEffect(() => {
    qc.invalidateQueries({ queryKey: ["dashboard-rows"] });
    qc.invalidateQueries({ queryKey: ["dashboard-analytics"] });
  }, [marketSessionActive, marketPhase, qc]);

  const data = query.data;
  const fallbackBySymbol = useMemo(() => {
    const rows = new Map<string, any>();
    for (const row of data?.rows ?? []) rows.set(String(row.Symbol).toUpperCase(), row);
    return rows;
  }, [data?.rows]);
  const analyticsBySymbol = useMemo(() => {
    const rows = new Map<string, any>();
    for (const row of analyticsQuery.data?.rows ?? []) rows.set(String(row.Symbol).toUpperCase(), row);
    return rows;
  }, [analyticsQuery.data?.rows]);
  type CachedRow = {
    live: MarketQuote | undefined;
    fallback: any;
    analyticsFallback: any;
    warrant: CoveredWarrant | undefined;
    underlyingQuote: MarketQuote | undefined;
    sessionDate: string | undefined;
    active: boolean;
    tracked: boolean;
    freshnessBucket: number;
    value: DashboardRow | undefined;
  };
  const rowCache = useRef(new Map<string, CachedRow>());

  const getRow = useCallback((symbol: string): DashboardRow | undefined => {
    const sym = symbol.toUpperCase();
    const live = quotes.get(sym);
    const fb = fallbackBySymbol.get(sym);
    const analyticsFallback = analyticsBySymbol.get(sym);
    const cw = warrants?.get(sym);
    const underlyingQuote = cw?.underlyingSymbol ? quotes.get(cw.underlyingSymbol) : undefined;
    const sessionDate = sessionContext?.displaySessionDate;
    const tracked = isRealtimeTracked(sym);
    const now = marketNow();
    // Re-evaluate age-based provenance even when a quiet symbol has not produced a new
    // object. Five-second buckets keep STALE transitions truthful without rebuilding every
    // row on every 80 ms render batch.
    const freshnessBucket = Math.floor(now / 5_000);
    const cached = rowCache.current.get(sym);

    if (
      cached &&
      cached.live === live &&
      cached.fallback === fb &&
      cached.analyticsFallback === analyticsFallback &&
      cached.warrant === cw &&
      cached.underlyingQuote === underlyingQuote &&
      cached.sessionDate === sessionDate &&
      cached.active === marketSessionActive &&
      cached.tracked === tracked &&
      cached.freshnessBucket === freshnessBucket
    ) {
      return cached.value;
    }

    if (!fb && !live) {
      rowCache.current.set(sym, {
        live, fallback: fb, analyticsFallback, warrant: cw, underlyingQuote,
        sessionDate, active: marketSessionActive, tracked, freshnessBucket, value: undefined,
      });
      return undefined;
    }
    const fallbackQuote = mapRawSnapshotToQuote(fb ?? { Symbol: sym });
    const sourceProvenance = (fb?.provenance ?? {
      quote: { state: "UNAVAILABLE", source: "NONE" },
      book: { state: "UNAVAILABLE", source: "NONE" },
    }) as RowProvenance;
    const provenance: RowProvenance = {
      ...sourceProvenance,
      quote: { ...sourceProvenance.quote },
      book: { ...sourceProvenance.book },
      ...(sourceProvenance.analytics ? { analytics: { ...sourceProvenance.analytics } } : {}),
      ...(analyticsFallback?.provenance
        ? { analytics: { ...analyticsFallback.provenance } }
        : {}),
    };
    const resolved = resolveDashboardQuote(fallbackQuote, live, provenance, marketSessionActive, now, sessionContext?.displaySessionDate);
    const analytics = resolveDashboardAnalytics(
      [cw?.analyticsSnapshot, analyticsFallback?.analytics, fb?.analytics], resolved.quote,
      sessionDate ?? resolved.provenance.quote.sessionDate,
      underlyingQuote,
    );

    const value: DashboardRow = {
      symbol: sym,
      ...resolved,
      analytics,
      trackedRealtime: Boolean(fb?.tracked_realtime ?? tracked),
    };
    rowCache.current.set(sym, {
      live, fallback: fb, analyticsFallback, warrant: cw, underlyingQuote,
      sessionDate, active: marketSessionActive, tracked, freshnessBucket, value,
    });
    return value;
  }, [
    analyticsBySymbol,
    fallbackBySymbol,
    isRealtimeTracked,
    marketSessionActive,
    quotes,
    sessionContext?.displaySessionDate,
    warrants,
  ]);

  const meta: DashboardMeta = data
    ? {
        asOf: data.as_of ?? null,
        marketSession: data.market_session ?? "UNKNOWN",
        marketSessionActive: Boolean(data.market_session_active),
        latestCompletedSession: data.latest_completed_session ?? null,
        calendarConfidence: data.calendar_confidence ?? null,
      }
    : EMPTY_META;

  return {
    getRow,
    meta,
    isLoading: query.isLoading,
    isError: query.isError,
    refetch: () => Promise.all([query.refetch(), analyticsQuery.refetch()]),
  };
}
