import { useQuery } from "@tanstack/react-query";
import type { HistoricalBar } from "@/domain/models";
import type { ChartInterval } from "@/domain/historical/types";
import { queryKeys } from "./query_keys";
import { fetchHistoricalBars } from "./historical_bars";

export interface UseHistoricalBarsArgs {
  symbol: string | null | undefined;
  timeframe: string;
  interval: ChartInterval | string;
  adjusted?: boolean;
  enabled?: boolean;
}

export interface HistoricalBarsResult {
  bars: HistoricalBar[];
  isLoading: boolean; // first load, nothing to show yet
  isFetching: boolean; // background refetch in progress
  isError: boolean;
  error: unknown;
  /** true only when the query has resolved successfully with an empty series */
  isEmpty: boolean;
  refetch: () => void;
}

/**
 * Server state for one chart request. TanStack Query provides:
 *  - dedupe of concurrent identical requests (query key),
 *  - cache reuse across drawer open/close and symbol re-selection (staleTime/gcTime),
 *  - distinct cache entries per symbol/timeframe/interval/adjusted (the key),
 *  - AbortSignal cancellation of superseded requests on fast navigation.
 */
export function useHistoricalBars({
  symbol,
  timeframe,
  interval,
  adjusted = true,
  enabled = true,
}: UseHistoricalBarsArgs): HistoricalBarsResult {
  const sym = (symbol ?? "").trim().toUpperCase();
  const active = enabled && sym.length > 0;

  const query = useQuery({
    queryKey: queryKeys.history.bars({ symbol: sym, timeframe, interval, adjusted }),
    queryFn: ({ signal }) => fetchHistoricalBars({ symbol: sym, timeframe, interval, adjusted }, signal),
    enabled: active,
  });

  const bars = query.data ?? [];
  return {
    bars,
    isLoading: active && query.isLoading,
    isFetching: query.isFetching,
    isError: query.isError,
    error: query.error,
    isEmpty: query.isSuccess && bars.length === 0,
    refetch: () => {
      void query.refetch();
    },
  };
}
