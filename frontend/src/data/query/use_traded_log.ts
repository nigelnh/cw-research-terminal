import { useMarketContext } from "@/data/market_session_store";
import { useSyncExternalStore } from "react";
import { useQuery } from "@tanstack/react-query";
import { backendClient } from "@/data/backend/backend_client";
import { tradePrintStore, tradePrintKey, type TradePrint } from "@/data/backend/trade_print_store";

/** The server retains this many prints per symbol; asking for more would gain nothing. */
const SESSION_LIMIT = 8000;
/** The repair poll only has to cover prints the socket could have dropped in a gap. */
const REPAIR_LIMIT = 300;

/**
 * Time & sales for the instrument panel.
 *
 * Three sources, deliberately:
 *
 * * The **shared observed window** - one fetch of the server-side tape when the panel opens.
 *   Redis makes it the same on every machine and survives backend restarts. When a provider
 *   offers confirmed intraday history it can backfill earlier prints; SSI-only coverage
 *   begins when the backend observes latest-match transitions.
 * * **Live prints** over the WebSocket, on the same tick path as the quote patches that
 *   drive STATS and the watchlist row - polling REST alone left the tape running seconds
 *   behind them.
 * * A small **repair poll**, to pick up anything missed while the socket was down. It asks
 *   for a short recent window rather than the session, so the periodic cost stays trivial.
 *
 * The three are merged and de-duplicated by provider identity when available, with a full
 * observation footprint as the fallback.
 *
 * The server keeps the tape until 08:00 ICT the morning after its session, so this still
 * has the day's prints after the close.
 */
export function useTradedLog(symbol: string | null | undefined, marketSessionActive: boolean) {
  const sym = (symbol ?? "").trim().toUpperCase();
  const { sessionContext } = useMarketContext();
  const day = sessionContext?.displaySessionDate;

  const session = useQuery({
    queryKey: ["traded-log", sym, "session", day],
    enabled: sym.length > 0,
    queryFn: ({ signal }) => backendClient.getTradedLog(sym, SESSION_LIMIT, signal),
    // History does not change behind us - only grows, and growth arrives on the socket.
    staleTime: 60_000,
    refetchOnWindowFocus: true,
    refetchOnReconnect: true,
    gcTime: 30 * 60_000,
    retry: 1,
  });

  const repair = useQuery({
    queryKey: ["traded-log", sym, "repair", day],
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
    if (day && p.session_date !== day) continue;
    byKey.set(tradePrintKey(p), p);
  }
  const items = [...byKey.values()].sort((a, b) => b.ts - a.ts);

  return {
    items,
    coverage: "Observed window",
    truncated: Boolean(session.data?.truncated || items.length >= SESSION_LIMIT),
    sessionDate:
      day ?? items[0]?.session_date ?? session.data?.session_date ?? repair.data?.session_date ?? null,
    sideBasis: session.data?.side_basis ?? repair.data?.side_basis ?? null,
    isLoading: sym.length > 0 && session.isLoading && repair.isLoading && items.length === 0,
    isError: session.isError && repair.isError && items.length === 0,
  };
}
