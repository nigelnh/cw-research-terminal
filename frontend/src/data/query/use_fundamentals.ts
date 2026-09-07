import { useQuery } from "@tanstack/react-query";
import { backendClient } from "@/data/backend/backend_client";

/**
 * Valuation and quarterly statement lines for one equity.
 *
 * Valuation moves once a day and statements once a quarter, so this is cached hard on both
 * sides and never polled: the QUANT tab is a reading surface, not a ticking one.
 */
export function useFundamentals(symbol: string | null | undefined, enabled = true) {
  const sym = (symbol ?? "").trim().toUpperCase();
  const query = useQuery({
    queryKey: ["fundamentals", sym],
    enabled: enabled && sym.length > 0,
    queryFn: ({ signal }) => backendClient.getFundamentals(sym, signal),
    staleTime: 30 * 60_000,
    gcTime: 60 * 60_000,
    retry: 1,
  });
  return {
    data: query.data ?? null,
    quarters: query.data?.quarters ?? [],
    isLoading: enabled && sym.length > 0 && query.isLoading,
    isError: query.isError,
  };
}
