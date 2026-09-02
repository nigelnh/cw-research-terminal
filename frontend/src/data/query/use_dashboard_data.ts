import { useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { MarketQuote } from "@/domain/models";
import {
  quoteTimestamp,
  type DisplayState,
  type RowProvenance,
} from "@/domain/temporal";
import { backendClient } from "@/data/backend/backend_client";
import { mapRawSnapshotToQuote } from "@/data/backend/mappers/map_snapshot";
import { useResearchMarket } from "@/data/use_research_market";

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

export function isQuoteTimestampEligible(
  stamp: string | null,
  now = Date.now(),
): boolean {
  if (!stamp) return false;
  const age = now - new Date(stamp).getTime();
  return Number.isFinite(age) && age >= 0 && age <= 86400_000;
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
  const { quotes, marketSessionActive } = useResearchMarket();
  const qc = useQueryClient();

  const sortedKey = [...new Set(symbols.map((s) => s.toUpperCase()))].sort();
  const query = useQuery({
    queryKey: ["dashboard-rows", sortedKey],
    enabled: sortedKey.length > 0,
    queryFn: ({ signal }) => backendClient.getDashboardRows(sortedKey, signal),
    staleTime: 30_000,
    refetchInterval: marketSessionActive ? false : 5 * 60_000, // idle refresh while closed
  });

  // Refetch immediately when the session transitions (closed -> open must not keep showing
  // last-session, open -> closed must fill the fallback).
  useEffect(() => {
    qc.invalidateQueries({ queryKey: ["dashboard-rows"] });
  }, [marketSessionActive, qc]);

  const data = query.data;
  const fallbackBySymbol = new Map<string, any>();
  for (const row of data?.rows ?? []) {
    fallbackBySymbol.set(String(row.Symbol).toUpperCase(), row);
  }

  const getRow = (symbol: string): DashboardRow | undefined => {
    const sym = symbol.toUpperCase();
    const live = quotes.get(sym);
    const fb = fallbackBySymbol.get(sym);

    // Live wins only while the session is active AND we actually have a fresh tick.
    const liveUsable =
      marketSessionActive &&
      !!live &&
      live.lastPrice != null &&
      isQuoteTimestampEligible(quoteTimestamp(live));

    if (liveUsable && live) {
      return {
        symbol: sym,
        quote: live,
        provenance: {
          quote: {
            state: "LIVE",
            source: "LIVE_FEED",
            asOf: quoteTimestamp(live),
            sessionDate: null,
          },
          book: { state: "LIVE", source: "LIVE_FEED" },
        },
        displayState: "LIVE",
        analytics: fb?.analytics ?? null,
        trackedRealtime: true,
      };
    }

    if (!fb) return undefined;
    return {
      symbol: sym,
      quote: mapRawSnapshotToQuote(fb),
      provenance: (fb.provenance ?? {
        quote: { state: "UNAVAILABLE", source: "NONE" },
        book: { state: "UNAVAILABLE", source: "NONE" },
      }) as RowProvenance,
      displayState: (fb.displayState ?? "UNAVAILABLE") as DisplayState,
      analytics: fb.analytics ?? null,
      trackedRealtime: Boolean(fb.tracked_realtime),
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
    refetch: query.refetch,
  };
}
