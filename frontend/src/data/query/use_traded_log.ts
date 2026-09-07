import { useSyncExternalStore } from "react";
import { useQuery } from "@tanstack/react-query";
import { backendClient } from "@/data/backend/backend_client";
import { tradePrintStore, type TradePrint } from "@/data/backend/trade_print_store";

/** The server retains this many prints per symbol; asking for more would gain nothing. */
const SESSION_LIMIT = 8000;
/** The repair poll only has to cover prints the socket could have dropped in a gap. */
const REPAIR_LIMIT = 300;

/**
 * Time & sales for the instrument panel.
 *
 * Three sources, deliberately:
 *
 * * The **session archive** - one fetch of the whole server-side tape when the panel opens
 *   on a symbol. This is what makes the log the same on every machine: the tape lives in
 *   Redis, so a laptop opening at 14:00 gets the morning's prints it was never connected
 *   for, instead of starting blank. It is a large response, so it is fetched once and not
 *   polled - the socket keeps it current from there.
 * * **Live prints** over the WebSocket, on the same tick path as the quote patches that
 *   drive STATS and the watchlist row - polling REST alone left the tape running seconds
 *   behind them.
 * * A small **repair poll**, to pick up anything missed while the socket was down. It asks
 *   for a short recent window rather than the session, so the periodic cost stays trivial.
 *
 * The three are merged and de-duplicated on the exchange timestamp, so overlap is free.
 *
 * The server keeps the tape until 08:00 ICT the morning after its session, so this still
 * has the day's prints after the close.
 */
export function useTradedLog(symbol: string | null | undefined, marketSessionActive: boolean) {
  const sym = (symbol ?? "").trim().toUpperCase();

  const session = useQuery({
    queryKey: ["traded-log", sym, "session"],
    enabled: sym.length > 0,
    queryFn: ({ signal }) => backendClient.getTradedLog(sym, SESSION_LIMIT, signal),
    // History does not change behind us - only grows, and growth arrives on the socket.
    staleTime: Infinity,
    gcTime: 30 * 60_000,
    retry: 1,
  });

  const repair = useQuery({
    queryKey: ["traded-log", sym, "repair"],
    enabled: sym.length > 0,
    queryFn: ({ signal }) => backendClient.getTradedLog(sym, REPAIR_LIMIT, signal),
    staleTime: 10_000,
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

  const archived = session.data?.items ?? [];
  const recent = repair.data?.items ?? [];
  const live = sym ? tradePrintStore.get(sym) : [];

  const byKey = new Map<string, TradePrint>();
  for (const p of [...archived, ...recent, ...live] as TradePrint[]) {
    byKey.set(`${p.ts}|${p.price}|${p.volume ?? ""}`, p);
  }
  const items = [...byKey.values()].sort((a, b) => b.ts - a.ts);

  return {
    items,
    sessionDate:
      items[0]?.session_date ?? session.data?.session_date ?? repair.data?.session_date ?? null,
    sideBasis: session.data?.side_basis ?? repair.data?.side_basis ?? null,
    isLoading: sym.length > 0 && session.isLoading && repair.isLoading && items.length === 0,
    isError: session.isError && repair.isError && items.length === 0,
  };
}
