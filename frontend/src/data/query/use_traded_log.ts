import { useSyncExternalStore } from "react";
import { useQuery } from "@tanstack/react-query";
import { backendClient } from "@/data/backend/backend_client";
import { tradePrintStore, type TradePrint } from "@/data/backend/trade_print_store";

/**
 * Time & sales for the instrument panel.
 *
 * Live prints arrive over the WebSocket, on the same tick path as the quote patches that
 * drive STATS and the watchlist row - polling REST alone left the tape running seconds
 * behind them. REST remains the backfill for prints that happened before the panel opened,
 * and the safety net if the socket is down; the two are merged and de-duplicated on the
 * exchange timestamp.
 *
 * The server keeps the tape until 08:00 ICT the morning after its session, so this still
 * has the day's prints after the close.
 */
export function useTradedLog(symbol: string | null | undefined, marketSessionActive: boolean) {
  const sym = (symbol ?? "").trim().toUpperCase();

  const query = useQuery({
    queryKey: ["traded-log", sym],
    enabled: sym.length > 0,
    queryFn: ({ signal }) => backendClient.getTradedLog(sym, 100, signal),
    staleTime: 10_000,
    // The socket carries the live prints now, so this is backfill/repair, not the pulse.
    refetchInterval: marketSessionActive ? 30_000 : 5 * 60_000,
    refetchIntervalInBackground: true,
    refetchOnWindowFocus: true,
    retry: 1,
  });

  useSyncExternalStore(
    tradePrintStore.subscribe,
    tradePrintStore.getRevision,
    tradePrintStore.getRevision,
  );

  const fetched = query.data?.items ?? [];
  const live = sym ? tradePrintStore.get(sym) : [];

  const byKey = new Map<string, TradePrint>();
  for (const p of [...fetched, ...live] as TradePrint[]) {
    byKey.set(`${p.ts}|${p.price}|${p.volume ?? ""}`, p);
  }
  const items = [...byKey.values()].sort((a, b) => b.ts - a.ts).slice(0, 100);

  return {
    items,
    sessionDate: items[0]?.session_date ?? query.data?.session_date ?? null,
    sideBasis: query.data?.side_basis ?? null,
    isLoading: sym.length > 0 && query.isLoading && items.length === 0,
    isError: query.isError && items.length === 0,
  };
}
