import { useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { MarketQuote } from "@/domain/models";
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
  const { quotes, marketSessionActive, marketPhase, isRealtimeTracked } = useResearchMarket();
  const qc = useQueryClient();

  const sortedKey = [...new Set(symbols.map((s) => s.toUpperCase()))].sort();
  const query = useQuery({
    queryKey: ["dashboard-rows", sortedKey],
    enabled: sortedKey.length > 0,
    queryFn: ({ signal }) => backendClient.getDashboardRows(sortedKey, signal),
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
    queryKey: ["dashboard-analytics", sortedKey],
    enabled: sortedKey.length > 0,
    queryFn: ({ signal }) => backendClient.getDashboardAnalytics(sortedKey, signal),
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

  // 08:00 is a data rollover, not a trading-phase change. Refresh open overnight tabs
  // even if there are no new ticks; the server calendar decides weekends/holidays.
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    const schedule = () => {
      const now = Date.now();
      const day = new Date(now + 7 * 3600_000).toISOString().slice(0, 10);
      let next = Date.parse(`${day}T08:00:00+07:00`);
      if (next <= now) next += 86400_000;
      timer = setTimeout(() => {
        qc.invalidateQueries({ queryKey: ["dashboard-rows"] });
        qc.invalidateQueries({ queryKey: ["dashboard-analytics"] });
        schedule();
      }, next - now);
    };
    schedule();
    return () => clearTimeout(timer);
  }, [qc]);

  const data = query.data;
  const fallbackBySymbol = new Map<string, any>();
  for (const row of data?.rows ?? []) {
    fallbackBySymbol.set(String(row.Symbol).toUpperCase(), row);
  }
  const analyticsBySymbol = new Map<string, any>();
  for (const row of analyticsQuery.data?.rows ?? []) {
    analyticsBySymbol.set(String(row.Symbol).toUpperCase(), row);
  }

  const getRow = (symbol: string): DashboardRow | undefined => {
    const sym = symbol.toUpperCase();
    const live = quotes.get(sym);
    const fb = fallbackBySymbol.get(sym);
    const analyticsFallback = analyticsBySymbol.get(sym);

    if (!fb && !live) return undefined;
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
    const resolved = resolveDashboardQuote(fallbackQuote, live, provenance, marketSessionActive);
    const analytics = analyticsFallback?.analytics ?? fb?.analytics ?? null;
    // IV and the Greeks are computed FROM the prices in this row. The two come from
    // separate endpoints with separate session policies, so after the 08:00 ICT rollover
    // the price row correctly blanks for the new session while the quant read still
    // answers with the previous session's EOD figures - leaving a row showing IV_BID
    // 42.5% beside an empty BID_PRC. A derived number outliving the number it was derived
    // from reads as live data, so it is dropped rather than shown undated.
    const analyticsSession = provenance.analytics?.sessionDate ?? null;
    const rowSession = provenance.quote?.sessionDate ?? null;
    const strandedByRollover =
      Boolean(analyticsSession && rowSession && analyticsSession < rowSession) &&
      resolved.quote.lastPrice == null &&
      resolved.quote.bidPrice == null &&
      resolved.quote.askPrice == null;

    return {
      symbol: sym,
      ...resolved,
      analytics: strandedByRollover ? null : analytics,
      trackedRealtime: Boolean(fb?.tracked_realtime ?? isRealtimeTracked(sym)),
    };
  };

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
