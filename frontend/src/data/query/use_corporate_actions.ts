import { useQuery } from "@tanstack/react-query";
import type { CorporateActionItem } from "@/domain/models";
import { backendClient } from "@/data/backend/backend_client";
import { queryKeys } from "./query_keys";

export interface CorporateActionsResult {
  items: CorporateActionItem[];
  isLoading: boolean;
  isFetching: boolean;
  isError: boolean;
  isEmpty: boolean;
  refetch: () => void;
}

/**
 * Server state for one symbol's corporate-action history (dividends, meetings,
 * rights issues …). PostgreSQL-backed; an un-ingested symbol resolves to an
 * empty list, surfaced as `isEmpty`.
 */
export function useCorporateActions(
  symbol: string | null | undefined,
  opts: { limit?: number; enabled?: boolean } = {}
): CorporateActionsResult {
  const sym = (symbol ?? "").trim().toUpperCase();
  const active = (opts.enabled ?? true) && sym.length > 0;

  const result = useQuery({
    queryKey: queryKeys.research.corporateActions(sym),
    queryFn: ({ signal }) => backendClient.getCorporateActions(sym, opts.limit, signal),
    enabled: active,
    staleTime: 5 * 60_000,
  });

  const items = result.data?.items ?? [];
  return {
    items,
    isLoading: active && result.isLoading,
    isFetching: result.isFetching,
    isError: result.isError,
    isEmpty: result.isSuccess && items.length === 0,
    refetch: () => {
      void result.refetch();
    },
  };
}
