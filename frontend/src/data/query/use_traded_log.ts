import { useQuery } from "@tanstack/react-query";
import { backendClient } from "@/data/backend/backend_client";

/**
 * Time & sales for the instrument panel.
 *
 * The tape is server-side and kept until 08:00 ICT the morning after its session, so this
 * keeps polling after the close - the panel still has the day's prints. Polls faster while
 * the market is open, and (like the other market reads) keeps running in a background tab
 * so returning to the terminal does not show a frozen tape.
 */
export function useTradedLog(symbol: string | null | undefined, marketSessionActive: boolean) {
  const sym = (symbol ?? "").trim().toUpperCase();
  const query = useQuery({
    queryKey: ["traded-log", sym],
    enabled: sym.length > 0,
    queryFn: ({ signal }) => backendClient.getTradedLog(sym, 50, signal),
    staleTime: 3_000,
    refetchInterval: marketSessionActive ? 5_000 : 60_000,
    refetchIntervalInBackground: true,
    refetchOnWindowFocus: true,
    retry: 1,
  });
  return {
    items: query.data?.items ?? [],
    sessionDate: query.data?.session_date ?? null,
    sideBasis: query.data?.side_basis ?? null,
    isLoading: sym.length > 0 && query.isLoading,
    isError: query.isError,
  };
}
