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
  sparkline: Array<number | { timestamp: string; value: number; reference?: number | null }>;
  provenance?: Record<string, { source: string; as_of?: string | null; session_date?: string | null; availability?: string }>;
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
}

export function useMarketOverview() {
  return useQuery<MarketOverviewData>({
    queryKey: queryKeys.marketOverview,
    queryFn: ({ signal }) => backendClient.getMarketOverview(signal),
    staleTime: 60_000,
    refetchInterval: 5 * 60_000,
    retry: 1,
  });
}
