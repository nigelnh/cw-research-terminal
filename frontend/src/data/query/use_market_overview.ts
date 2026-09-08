import { acceptMarketContext, useMarketContext, type SessionContext, type FeedStatus } from "@/data/market_session_store";
import { useQuery } from "@tanstack/react-query";
import { backendClient } from "@/data/backend/backend_client";
import { queryKeys } from "./query_keys";

export interface IndexOverview {
  symbol: string;
  value: number | null;
  change: number | null;
  change_percent: number | null;
  volume: number | null;
  trading_value: number | null;
  advancing: number | null;
  ceiling: number | null;
  unchanged: number | null;
  declining: number | null;
  floor: number | null;
  as_of: string | null;
  reference?: number | null;
  session_date?: string | null;
  availability?: "AVAILABLE" | "PARTIAL" | "UNAVAILABLE";
  stale?: boolean;
  update_mode?: "POLLED";
  partial_reasons?: string[];
  sparkline: Array<
    number | { timestamp: string; value: number; reference?: number | null; volume?: number | null }
  >;
  provenance?: Record<string, { source: string; as_of?: string | null; session_date?: string | null; availability?: string; timeframe?: string }>;
}
export interface VolumeLeader {
  symbol: string;
  volume: number;
  price: number | null;
  reference?: number | null;
  ceiling?: number | null;
  floor?: number | null;
  market_state?: "CEILING" | "FLOOR" | "REFERENCE" | "UP" | "DOWN" | "UNAVAILABLE";
  as_of: string | null;
}
export interface MarketOverviewData {
  sessionContext?: SessionContext;
  feedStatus?: FeedStatus | null;
  unavailable_reason?: string;
  indices: IndexOverview[];
  top_stock_volume: VolumeLeader[];
  top_cw_volume: VolumeLeader[];
  as_of: string | null;
  market_session_active: boolean;
  stock_scope: string;
  cw_scope: string;
  source: string;
  market_phase?: string;
  availability?: string;
  stale?: boolean;
  refreshing?: boolean;
  cache_age_seconds?: number;
}

export function useMarketOverview() {
  const { sessionContext } = useMarketContext();
  return useQuery<MarketOverviewData>({
    queryKey: [...queryKeys.marketOverview, sessionContext?.displaySessionDate],
    queryFn: async ({ signal }) => { const data = await backendClient.getMarketOverview(signal); acceptMarketContext(data); return data; },
    staleTime: 60_000,
    refetchInterval: (query) => overviewRefetchInterval(query.state.data),
    // A market surface must not rot while the tab sits in the background. React Query
    // suspends `refetchInterval` for a hidden document by default, so switching away
    // froze the index cards and coming back showed a stale board that only caught up at
    // the next tick. Keep polling, and repaint immediately on focus.
    refetchIntervalInBackground: true,
    refetchOnWindowFocus: true,
    retry: 1,
  });
}

export function overviewRefetchInterval(data?: MarketOverviewData): number {
  if (data?.refreshing) return 2_000;
  if (!data || data.availability === "UNAVAILABLE") return 15_000;
  // Backend refreshes a single shared snapshot every 60s in-session; polling
  // five minutes apart left every visible tab stale between refreshes.
  return data.market_session_active ? 15_000 : 60_000;
}
