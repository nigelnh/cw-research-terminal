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
  return Number.isFinite(age) && age >= 0 && age <= 180_000;
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
  const { quotes, marketSessionActive, isRealtimeTracked } = useResearchMarket();
  const qc = useQueryClient();

  const sortedKey = [...new Set(symbols.map((s) => s.toUpperCase()))].sort();
  const query = useQuery({
    queryKey: ["dashboard-rows", sortedKey],
    enabled: sortedKey.length > 0,
    queryFn: ({ signal }) => backendClient.getDashboardRows(sortedKey, signal),
    staleTime: 30_000,
    refetchInterval: marketSessionActive ? false : 5 * 60_000, // idle refresh while closed
  });
  const analyticsQuery = useQuery({
    queryKey: ["dashboard-analytics", sortedKey],
    enabled: sortedKey.length > 0,
    queryFn: ({ signal }) => backendClient.getDashboardAnalytics(sortedKey, signal),
    // Live analytics arrive over WS. This read is the independently hydrated EOD/current
    // cache and may finish later without delaying the quote table.
    staleTime: marketSessionActive ? 30_000 : 5 * 60_000,
  });

  // Refetch immediately when the session transitions (closed -> open must not keep showing
  // last-session, open -> closed must fill the fallback).
  useEffect(() => {
    qc.invalidateQueries({ queryKey: ["dashboard-rows"] });
    qc.invalidateQueries({ queryKey: ["dashboard-analytics"] });
  }, [marketSessionActive, qc]);

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
    const tradeAsOf = quoteTimestamp(live);
    const bookAsOf = live?.bookTimestamp && Number.isFinite(live.bookTimestamp)
      ? new Date(live.bookTimestamp).toISOString() : null;
    const correctSession = !!live?.marketSessionDate && live.marketSessionDate === data?.as_of?.slice(0, 10);
    const tradeLive = marketSessionActive && correctSession && isQuoteTimestampEligible(tradeAsOf);
    const bookLive = marketSessionActive && correctSession && isQuoteTimestampEligible(bookAsOf);
    const quote = { ...fallbackQuote };
    if (live && tradeLive) {
      Object.assign(quote, {
        lastPrice: live.lastPrice, openPrice: live.openPrice, highPrice: live.highPrice,
        lowPrice: live.lowPrice, averagePrice: live.averagePrice,
        tradedQuantity: live.tradedQuantity, totalVolume: live.totalVolume,
        tradingValue: live.tradingValue, priceChange: live.priceChange,
        priceChangePercent: live.priceChangePercent, tradeTimestamp: live.tradeTimestamp,
        sourceTimestamp: live.sourceTimestamp,
      });
      provenance.quote = { state: "LIVE", source: "LIVE_FEED", asOf: tradeAsOf,
        sessionDate: live.marketSessionDate };
    }
    if (live && bookLive) {
      Object.assign(quote, {
        bidPrice: live.bidPrice, bidQuantity: live.bidQuantity,
        askPrice: live.askPrice, askQuantity: live.askQuantity,
        bid2Price: live.bid2Price, bid2Quantity: live.bid2Quantity,
        ask2Price: live.ask2Price, ask2Quantity: live.ask2Quantity,
        bid3Price: live.bid3Price, bid3Quantity: live.bid3Quantity,
        ask3Price: live.ask3Price, ask3Quantity: live.ask3Quantity,
        bookTimestamp: live.bookTimestamp,
      });
      provenance.book = { state: "LIVE", source: "LIVE_FEED", asOf: bookAsOf,
        sessionDate: live.marketSessionDate };
    }
    const anyLive = tradeLive || bookLive;
    return {
      symbol: sym,
      quote,
      provenance,
      displayState: (tradeLive && bookLive ? "LIVE" : anyLive ? "MIXED" : fb?.displayState ?? "UNAVAILABLE") as DisplayState,
      analytics: analyticsFallback?.analytics ?? fb?.analytics ?? null,
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
