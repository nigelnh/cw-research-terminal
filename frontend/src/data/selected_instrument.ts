import type { CoveredWarrant, MarketQuote, WatchlistItem } from "@/domain/models";
import type { InstrumentSpec } from "@/data/instruments/use_instrument_specs";

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
  dataQuality?: "COMPLETE" | "PARTIAL" | null;
  metadataVerification?: "VERIFIED_CURRENT" | "CONFLICTING" | "STALE" | "UNVERIFIED" | null;
  quote?: MarketQuote;
  cw?: CoveredWarrant;
}

const looksLikeCw = (sym: string) => sym.startsWith("C") && sym.length >= 6;

export function deriveSelectedInstrument(
  symbol: string | null | undefined,
  sources: {
    /** Canonical contract metadata from the backend registry. Takes precedence over everything. */
    instrumentSpec?: InstrumentSpec | null;
    watchlistItem?: WatchlistItem | null;
    universeCw?: CoveredWarrant | null;
    quote?: MarketQuote;
    cw?: CoveredWarrant;
  }
): SelectedInstrumentView | null {
  if (!symbol) return null;
  const sym = symbol.trim().toUpperCase();
  const { instrumentSpec, watchlistItem, universeCw, quote, cw } = sources;

  // Contract-term precedence: canonical registry spec > research-universe record > realtime
  // store. The watchlist item contributes ONLY identity (symbol / type), never frozen terms.
  const meta = instrumentSpec ?? universeCw ?? null;
  const declaredType =
    (instrumentSpec?.instrumentType as SelectedInstrumentView["instrumentType"] | undefined) ??
    (watchlistItem?.instrumentType as SelectedInstrumentView["instrumentType"] | undefined) ??
    (universeCw ? "CW" : undefined);
  const instrumentType: SelectedInstrumentView["instrumentType"] =
    declaredType ?? (looksLikeCw(sym) ? "CW" : "STOCK");

  return {
    symbol: sym,
    instrumentType,
    underlyingSymbol:
      meta?.underlyingSymbol ?? watchlistItem?.underlyingSymbol ?? cw?.underlyingSymbol ?? null,
    issuer: meta?.issuer ?? cw?.issuer ?? null,
    strikePrice: meta?.strikePrice ?? cw?.strikePrice ?? null,
    exerciseRatio: meta?.exerciseRatio ?? cw?.exerciseRatio ?? null,
    maturityDate: meta?.maturityDate ?? cw?.maturityDate ?? null,
    lastTradingDate: meta?.lastTradingDate ?? cw?.lastTradingDate ?? null,
    dataQuality: instrumentSpec?.dataQuality ?? null,
    metadataVerification: instrumentSpec?.metadataVerification ?? null,
    quote: quote ?? cw?.quote,
    cw: cw ?? undefined,
  };
}
