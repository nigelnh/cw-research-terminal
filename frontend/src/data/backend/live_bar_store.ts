import { marketSessionStore } from "@/data/market_session_store";
import type { HistoricalBar } from "@/domain/models";

type Listener = () => void;
const bars = new Map<string, HistoricalBar>();
const listeners = new Set<Listener>();
let revision = 0;
const key = (symbol: string, timeframe: string) => `${symbol.toUpperCase()}|${timeframe}`;

export function acceptLiveBarMessage(message: any): void {
  const b = message?.bar;
  if (!b || !message.symbol || !message.timeframe || b.price_basis !== "RAW") return;
  const display = marketSessionStore.getSnapshot().sessionContext?.displaySessionDate;
  if (display && b.session_date !== display) return;
  const mapped: HistoricalBar = {
    symbol: String(message.symbol).toUpperCase(), date: String(b.date),
    open: Number.isFinite(b.open) ? b.open : null,
    high: Number.isFinite(b.high) ? b.high : null,
    low: Number.isFinite(b.low) ? b.low : null,
    close: Number.isFinite(b.close) ? b.close : null,
    volume: Number.isFinite(b.volume) ? b.volume : null,
    value: Number.isFinite(b.value) ? b.value : null,
    priceBasis: "RAW", source: String(b.source || "FIINQUANT_TRADE_STREAM"),
    sessionDate: b.session_date ?? null, complete: false, asOf: b.as_of ?? (message.ts ? new Date(message.ts).toISOString() : null),
  };
  const barKey = `${key(mapped.symbol, message.timeframe)}|${mapped.date}`;
  const previous = bars.get(barKey);
  if (previous?.asOf && (!mapped.asOf || Date.parse(mapped.asOf) < Date.parse(previous.asOf))) return;
  if (display) for (const [k, bar] of bars) if (bar.sessionDate !== display) bars.delete(k);
  bars.set(barKey, mapped);
  revision++;
  listeners.forEach((listener) => listener());
}

export const liveBarStore = {
  subscribe(listener: Listener) { listeners.add(listener); return () => listeners.delete(listener); },
  getRevision() { return revision; },
  get(symbol: string, timeframe: string) {
    const prefix = `${key(symbol, timeframe)}|`;
    return [...bars.entries()].filter(([k]) => k.startsWith(prefix)).map(([, bar]) => bar)
      .sort((a, b) => a.date.localeCompare(b.date));
  },
};
