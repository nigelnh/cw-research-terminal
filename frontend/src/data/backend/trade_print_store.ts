/**
 * Live time & sales, fed by the WebSocket.
 *
 * The tape used to be REST-only on a 5s poll, so it ran visibly behind STATS and the
 * watchlist row, which update on every tick. A print IS a tick, so it now arrives on the
 * tick path. REST is still the backfill for whatever happened before the panel opened.
 *
 * Bounded per symbol: the store follows every subscribed symbol, not just the open panel,
 * so an unbounded map would grow all session.
 */
export interface TradePrint {
  ts: number;
  time: string;
  price: number;
  change: number | null;
  change_percent: number | null;
  volume: number | null;
  side: "B" | "S" | null;
  session_date: string;
}

type Listener = () => void;

const MAX_PER_SYMBOL = 200;
const prints = new Map<string, TradePrint[]>();
const listeners = new Set<Listener>();
let revision = 0;

const key = (symbol: string) => symbol.trim().toUpperCase();

export function acceptTradePrintMessage(message: unknown): void {
  const m = message as { symbol?: unknown; print?: TradePrint } | null;
  const sym = typeof m?.symbol === "string" ? key(m.symbol) : "";
  const entry = m?.print;
  if (!sym || !entry || typeof entry.ts !== "number" || typeof entry.price !== "number") return;

  const tape = prints.get(sym) ?? [];
  // The same match can be re-delivered after a reconnect, and the REST backfill overlaps
  // with whatever arrived while it was in flight.
  if (tape.some((p) => p.ts === entry.ts && p.price === entry.price && p.volume === entry.volume)) {
    return;
  }
  tape.push(entry);
  tape.sort((a, b) => b.ts - a.ts);
  prints.set(sym, tape.slice(0, MAX_PER_SYMBOL));
  revision++;
  listeners.forEach((fn) => fn());
}

export const tradePrintStore = {
  subscribe(listener: Listener) {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },
  getRevision: () => revision,
  /** Newest first. */
  get(symbol: string): TradePrint[] {
    return prints.get(key(symbol)) ?? [];
  },
  /** Drops a symbol's tape when its session rolls over. */
  clear(symbol: string) {
    prints.delete(key(symbol));
    revision++;
    listeners.forEach((fn) => fn());
  },
};
