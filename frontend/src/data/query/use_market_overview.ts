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
  sparkline: number[];
}
export interface VolumeLeader { symbol: string; volume: number; price: number | null; as_of: string | null }
export interface MarketOverviewData {
  indices: IndexOverview[];
  top_stock_volume: VolumeLeader[];
  top_cw_volume: VolumeLeader[];
  as_of: string | null;
  market_session_active: boolean;
  stock_scope: string;
  cw_scope: string;
  source: string;
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
