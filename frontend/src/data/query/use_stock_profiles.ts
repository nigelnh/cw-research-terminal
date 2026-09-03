import { useQuery } from "@tanstack/react-query";
import { backendClient } from "@/data/backend/backend_client";
import { queryKeys } from "./query_keys";

export interface StockProfile {
  symbol: string;
  name: string | null;
  short_name: string | null;
  exchange: string | null;
}

const EMPTY: StockProfile[] = [];

/** Stable metadata reads, shared by watchlist suggestions and the registry. */
export function useStockProfiles(symbols: string[]) {
  const ordered = [...new Set(symbols.map(s => s.trim().toUpperCase()).filter(Boolean))].sort();
  const query = useQuery({
    queryKey: queryKeys.stockProfiles(ordered),
    queryFn: async ({ signal }) => {
      const batches = [];
      for (let i = 0; i < ordered.length; i += 60) batches.push(ordered.slice(i, i + 60));
      const results = await Promise.all(batches.map(batch => backendClient.getStockProfiles(batch, signal)));
      return results.flatMap(result => result.items);
    },
    enabled: ordered.length > 0,
    staleTime: 24 * 60 * 60_000,
    gcTime: 24 * 60 * 60_000,
    retry: 1,
    refetchOnWindowFocus: false,
  });
  return { profiles: query.data ?? EMPTY, isLoading: query.isLoading, isError: query.isError };
}
