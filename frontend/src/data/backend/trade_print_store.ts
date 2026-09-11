import { marketSessionStore } from "@/data/market_session_store";
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
  id?: string;
  cumulative_volume?: number | null;
  ts: number;
  time: string;
  price: number;
  change: number | null;
  change_percent: number | null;
  volume: number | null;
  side: "B" | "S" | null;
  session_date: string;
  source?: string;
  timestamp_basis?: string;
}

export const tradePrintKey = (p: TradePrint) => p.id ?? `${p.session_date}|${p.ts}|${p.price}|${p.volume ?? ""}|${p.cumulative_volume ?? ""}`;

type Listener = () => void;

// A session's worth of live prints, so the tape a long-open tab shows does not
// silently shrink to a shorter window than a freshly-opened one gets from the server.
const MAX_PER_SYMBOL = 8000;
const prints = new Map<string, TradePrint[]>();
const listeners = new Set<Listener>();
const identities = new Map<string, Set<string>>();
let revision = 0;

const key = (symbol: string) => symbol.trim().toUpperCase();

export function acceptTradePrintMessage(message: unknown): boolean {
  const m = message as { symbol?: unknown; print?: TradePrint } | null;
  const sym = typeof m?.symbol === "string" ? key(m.symbol) : "";
  const entry = m?.print;
  if (!sym || !entry || typeof entry.ts !== "number" || typeof entry.price !== "number") return false;

  const day = marketSessionStore.getSnapshot().sessionContext?.displaySessionDate;
  if (day && entry.session_date !== day) return false;
  const previous = prints.get(sym);
  const tape = previous?.[0]?.session_date === entry.session_date ? previous : [];
  const seen = tape === previous ? identities.get(sym)! : new Set<string>();
  const identity = tradePrintKey(entry);
  // The same match can be re-delivered after a reconnect, and the REST backfill overlaps
  // with whatever arrived while it was in flight.
  if (seen.has(identity)) {
    return false;
  }
  seen.add(identity);
  if (!tape.length || entry.ts >= tape[0].ts) tape.unshift(entry);
  else { tape.push(entry); tape.sort((a, b) => b.ts - a.ts); }
  if (tape.length > MAX_PER_SYMBOL) seen.delete(tradePrintKey(tape.pop()!));
  prints.set(sym, tape);
  identities.set(sym, seen);
  revision++;
  listeners.forEach((fn) => fn());
  return true;
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
    identities.delete(key(symbol));
    revision++;
    listeners.forEach((fn) => fn());
  },
};
