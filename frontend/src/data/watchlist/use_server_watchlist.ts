/**
 * The authenticated user's primary watchlist as TanStack Query server state.
 *
 * This is the ONLY place server watchlist state lives - there is no second global store.
 * The key is scoped by auth subject (`queryKeys.me.watchlist(sub)`), so a user switch can
 * never surface the previous user's list (and `queryClient.clear()` on identity change
 * wipes it regardless).
 */
import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { WatchlistItem } from "@/domain/models";
import { backendClient } from "@/data/backend/backend_client";
import { queryKeys } from "@/data/query/query_keys";
import { useAuth } from "@/data/auth";

type ServerItem = {
  symbol?: string;
  instrumentType?: string;
  underlyingSymbol?: string | null;
  issuer?: string | null;
  strikePrice?: number | null;
  exerciseRatio?: number | null;
  maturityDate?: string | null;
  lastTradingDate?: string | null;
  notes?: string | null;
};

export function mapServerToItems(raw: unknown): WatchlistItem[] {
  const list = Array.isArray(raw) ? raw : ((raw as { items?: unknown[] } | null)?.items ?? []);
  return (list as ServerItem[])
    .filter((it) => it && typeof it.symbol === "string" && it.symbol.length > 0)
    .map((it, idx) => ({
      symbol: String(it.symbol).toUpperCase(),
      instrumentType:
        it.instrumentType === "CW" ? "CW" : it.instrumentType === "INDEX" ? "INDEX" : "STOCK",
      underlyingSymbol: it.underlyingSymbol ? String(it.underlyingSymbol).toUpperCase() : null,
      issuer: it.issuer ?? null,
      strikePrice: typeof it.strikePrice === "number" ? it.strikePrice : null,
      exerciseRatio: typeof it.exerciseRatio === "number" ? it.exerciseRatio : null,
      maturityDate: it.maturityDate ?? null,
      lastTradingDate: it.lastTradingDate ?? null,
      addedAt: idx, // server order is authoritative; preserve it deterministically
      notes: it.notes ?? undefined,
    }));
}

/**
 * The PUT body carries ONLY what the user owns: symbol (membership + order) and an
 * optional note. Instrument/reference metadata is resolved canonically on the backend -
 * sending it would be ignored, so we don't.
 */
export function mapItemsToServer(items: WatchlistItem[]): Record<string, unknown>[] {
  return items.map((it) => ({
    symbol: it.symbol.toUpperCase(),
    notes: it.notes ?? null,
  }));
}

export interface ServerWatchlistHandle {
  /** true only when authenticated - callers fall back to the anonymous store otherwise. */
  isActive: boolean;
  items: WatchlistItem[];
  isLoading: boolean;
  isError: boolean;
  /** the query resolved and the server has no list yet (drives first-login import) */
  isResolvedEmpty: boolean;
  isSaving: boolean;
  /** Replace the whole list. Optimistically updates the user-scoped cache. */
  save: (items: WatchlistItem[]) => Promise<void>;
}

export function useServerWatchlist(): ServerWatchlistHandle {
  const { user, status } = useAuth();
  const queryClient = useQueryClient();
  const subject = user?.id ?? null;
  const isActive = status === "authenticated" && !!subject;

  const query = useQuery({
    queryKey: queryKeys.me.watchlist(subject ?? "__anon__"),
    queryFn: ({ signal }) => backendClient.getMyWatchlist(signal).then(mapServerToItems),
    enabled: isActive,
    staleTime: 30_000,
    retry: false, // never loop on 401/403
  });

  const mutation = useMutation({
    mutationFn: (items: WatchlistItem[]) =>
      backendClient.putMyWatchlist(mapItemsToServer(items)).then(mapServerToItems),
    onMutate: async (items: WatchlistItem[]) => {
      if (!subject) return { key: null, prev: undefined as WatchlistItem[] | undefined };
      const key = queryKeys.me.watchlist(subject);
      await queryClient.cancelQueries({ queryKey: key });
      const prev = queryClient.getQueryData<WatchlistItem[]>(key);
      queryClient.setQueryData(key, items); // optimistic
      return { key, prev };
    },
    onError: (_err, _items, ctx) => {
      if (ctx?.key) queryClient.setQueryData(ctx.key, ctx.prev);
    },
    onSuccess: (saved) => {
      if (subject) queryClient.setQueryData(queryKeys.me.watchlist(subject), saved);
    },
  });

  const { mutateAsync } = mutation;
  const save = useCallback(
    async (items: WatchlistItem[]) => {
      await mutateAsync(items);
    },
    [mutateAsync]
  );

  return {
    isActive,
    items: query.data ?? [],
    isLoading: isActive && query.isLoading,
    isError: query.isError,
    isResolvedEmpty: isActive && query.isSuccess && (query.data?.length ?? 0) === 0,
    isSaving: mutation.isPending,
    save,
  };
}
