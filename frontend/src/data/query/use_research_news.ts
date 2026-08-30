import { useQuery } from "@tanstack/react-query";
import type { ResearchNewsItem } from "@/domain/models";
import { backendClient } from "@/data/backend/backend_client";
import { queryKeys } from "./query_keys";

export interface UseResearchNewsArgs {
  /** Filter to disclosures linked to one symbol. */
  symbol?: string | null;
  /** Free-text headline filter (server-side ILIKE). */
  query?: string | null;
  lang?: "vi" | "en";
  limit?: number;
  enabled?: boolean;
}

export interface ResearchNewsResult {
  items: ResearchNewsItem[];
  isLoading: boolean;
  isFetching: boolean;
  isError: boolean;
  /** true only when the query resolved successfully with zero items */
  isEmpty: boolean;
  refetch: () => void;
}

/**
 * Server state for the PostgreSQL-backed research news feed. One key per
 * (symbol, query, lang); the backend returns a truthful empty list when nothing
 * has been ingested yet — that is `isEmpty`, not `isError`.
 */
export function useResearchNews({
  symbol,
  query,
  lang = "vi",
  limit = 40,
  enabled = true,
}: UseResearchNewsArgs = {}): ResearchNewsResult {
  const sym = (symbol ?? "").trim().toUpperCase() || undefined;
  const q = (query ?? "").trim() || undefined;

  const result = useQuery({
    queryKey: queryKeys.research.news({ symbol: sym ?? null, q: q ?? null, lang }),
    queryFn: ({ signal }) =>
      backendClient.getResearchNews({ symbol: sym, q, lang, limit }, signal),
    enabled,
    staleTime: 60_000,
  });

  const items = result.data?.items ?? [];
  return {
    items,
    isLoading: enabled && result.isLoading,
    isFetching: result.isFetching,
    isError: result.isError,
    isEmpty: result.isSuccess && items.length === 0,
    refetch: () => {
      void result.refetch();
    },
  };
}
