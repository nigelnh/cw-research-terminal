import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import type { ResearchFeedItem, FeedContentType } from "@/domain/models";
import { backendClient } from "@/data/backend/backend_client";
import { queryKeys } from "./query_keys";

export interface UseResearchFeedArgs {
  symbol?: string | null;
  symbols?: string[] | null;
  dateFrom?: string;
  dateTo?: string;
  source?: string | null;
  contentType?: FeedContentType | null;
  eventClass?: string | null;
  query?: string | null;
  lang?: "vi" | "en";
  pageSize?: number;
  enabled?: boolean;
}

export interface ResearchFeedResult {
  items: ResearchFeedItem[];
  isLoading: boolean;
  isFetching: boolean;
  isFetchingNextPage: boolean;
  isError: boolean;
  isEmpty: boolean;
  hasNextPage: boolean;
  fetchNextPage: () => void;
  refetch: () => void;
}

/**
 * The unified research feed with cursor pagination — never loads the whole corpus.
 * A ~2-year dataset stays server-side; the browser sees one page at a time and asks
 * for the next on demand.
 */
export function useResearchFeed({
  symbol,
  symbols,
  dateFrom,
  dateTo,
  source,
  contentType,
  eventClass,
  query,
  lang = "vi",
  pageSize = 40,
  enabled = true,
}: UseResearchFeedArgs = {}): ResearchFeedResult {
  const sym = (symbol ?? "").trim().toUpperCase() || undefined;
  const q = (query ?? "").trim() || undefined;

  const result = useInfiniteQuery({
    queryKey: queryKeys.research.feed({
      symbol: sym ?? null,
      symbols,
      dateFrom,
      dateTo,
      pageSize,
      source: source ?? null,
      contentType: contentType ?? null,
      eventClass: eventClass ?? null,
      q: q ?? null,
      lang,
    }),
    initialPageParam: undefined as
      { cursor?: string; before?: string } | undefined,
    queryFn: ({ pageParam, signal }) =>
      backendClient.getResearchFeed(
        {
          symbol: sym,
          symbols: symbols ?? undefined,
          date_from: dateFrom || undefined,
          date_to: dateTo || undefined,
          source: source ?? undefined,
          content_type: contentType ?? undefined,
          event_class: eventClass ?? undefined,
          q,
          lang,
          limit: pageSize,
          ...pageParam,
        },
        signal,
      ),
    getNextPageParam: (last) =>
      last.next_cursor
        ? { cursor: last.next_cursor }
        : last.next_before
          ? { before: last.next_before }
          : undefined,
    enabled,
    staleTime: 60_000,
  });

  const items = result.data?.pages.flatMap((p) => p.items) ?? [];
  return {
    items,
    isLoading: enabled && result.isLoading,
    isFetching: result.isFetching,
    isFetchingNextPage: result.isFetchingNextPage,
    isError: result.isError,
    isEmpty: result.isSuccess && items.length === 0,
    hasNextPage: !!result.hasNextPage,
    fetchNextPage: () => {
      if (result.hasNextPage && !result.isFetchingNextPage)
        void result.fetchNextPage();
    },
    refetch: () => {
      void result.refetch();
    },
  };
}

export function useFeedFacets() {
  return useQuery({
    queryKey: queryKeys.research.feedFacets,
    queryFn: ({ signal }) => backendClient.getFeedFacets(signal),
    staleTime: 10 * 60_000,
  });
}
