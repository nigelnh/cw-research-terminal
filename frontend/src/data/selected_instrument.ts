import type { CoveredWarrant, MarketQuote, WatchlistItem } from "@/domain/models";

/**
 * The shape the InstrumentDrawer / AI context consume. It is DERIVED at render time from
 * canonical sources - never stored:
 *   - contract metadata: the watchlist item OR the research-universe record
 *   - live quote / warrant analytics: the realtime WebSocket store
 */
export interface SelectedInstrumentView {
  symbol: string;
  instrumentType: "CW" | "STOCK" | "INDEX";
  underlyingSymbol?: string | null;
  issuer?: string | null;
  strikePrice?: number | null;
  exerciseRatio?: number | null;
  maturityDate?: string | null;
  lastTradingDate?: string | null;
  quote?: MarketQuote;
  cw?: CoveredWarrant;
}

const looksLikeCw = (sym: string) => sym.startsWith("C") && sym.length >= 6;

export function deriveSelectedInstrument(
  symbol: string | null | undefined,
  sources: {
    watchlistItem?: WatchlistItem | null;
    universeCw?: CoveredWarrant | null;
    quote?: MarketQuote;
    cw?: CoveredWarrant;
  }
): SelectedInstrumentView | null {
  if (!symbol) return null;
  const sym = symbol.trim().toUpperCase();
  const { watchlistItem, universeCw, quote, cw } = sources;

  const meta = watchlistItem ?? universeCw ?? null;
  const declaredType =
    (watchlistItem?.instrumentType as SelectedInstrumentView["instrumentType"] | undefined) ??
    (universeCw ? "CW" : undefined);
  const instrumentType: SelectedInstrumentView["instrumentType"] =
    declaredType ?? (looksLikeCw(sym) ? "CW" : "STOCK");

  return {
    symbol: sym,
    instrumentType,
    underlyingSymbol: meta?.underlyingSymbol ?? cw?.underlyingSymbol ?? null,
    issuer: meta?.issuer ?? cw?.issuer ?? null,
    strikePrice: meta?.strikePrice ?? cw?.strikePrice ?? null,
    exerciseRatio: meta?.exerciseRatio ?? cw?.exerciseRatio ?? null,
    maturityDate: meta?.maturityDate ?? cw?.maturityDate ?? null,
    lastTradingDate: meta?.lastTradingDate ?? cw?.lastTradingDate ?? null,
    quote: quote ?? cw?.quote,
    cw: cw ?? undefined,
  };
}
