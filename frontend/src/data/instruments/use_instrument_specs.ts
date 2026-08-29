import { useQuery } from "@tanstack/react-query";
import { useCallback } from "react";
import { backendClient } from "@/data/backend/backend_client";

/**
 * Canonical contract metadata for one instrument, straight from the backend
 * InstrumentRegistry (`GET /api/instruments`). This is the ONE source the UI uses for
 * issuer / underlying / strike / ratio / maturity / data-quality / verification.
 *
 * A watchlist item (localStorage or the server watchlist) stores identity + user
 * preference only; it never freezes contract terms. So when the registry is corrected,
 * every screen reflects it without the user clearing anything.
 */
export interface InstrumentSpec {
  symbol: string;
  instrumentType: "CW" | "STOCK" | "INDEX";
  issuer: string | null;
  underlyingSymbol: string | null;
  strikePrice: number | null; // effective
  exerciseRatio: number | null; // effective
  maturityDate: string | null;
  lastTradingDate: string | null;
  status: "ACTIVE" | "EXPIRED" | "UNKNOWN" | null;
  dataQuality: "COMPLETE" | "PARTIAL" | null;
  metadataVerification: "VERIFIED_CURRENT" | "CONFLICTING" | "STALE" | "UNVERIFIED" | null;
}

function mapSpec(raw: any): InstrumentSpec {
  const num = (v: any): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
  return {
    symbol: String(raw.symbol || "").toUpperCase(),
    instrumentType: raw.instrument_type === "CW" ? "CW" : raw.instrument_type === "INDEX" ? "INDEX" : "STOCK",
    issuer: raw.issuer || null,
    underlyingSymbol: raw.underlying_symbol ? String(raw.underlying_symbol).toUpperCase() : null,
    strikePrice: num(raw.effective_strike_price) ?? num(raw.strike_price),
    exerciseRatio: num(raw.effective_exercise_ratio) ?? num(raw.exercise_ratio),
    maturityDate: raw.maturity_date || null,
    lastTradingDate: raw.last_trading_date || null,
    status: raw.status ?? null,
    dataQuality: raw.data_quality ?? null,
    metadataVerification: raw.metadata_verification ?? null,
  };
}

const EMPTY = new Map<string, InstrumentSpec>();

export function useInstrumentSpecs() {
  const query = useQuery({
    queryKey: ["instrument-specs", "active"],
    queryFn: async () => {
      const items = await backendClient.getActiveInstruments();
      const m = new Map<string, InstrumentSpec>();
      for (const raw of items) {
        const s = mapSpec(raw);
        if (s.symbol) m.set(s.symbol, s);
      }
      return m;
    },
    staleTime: 10 * 60 * 1000, // contract terms change rarely
    gcTime: 30 * 60 * 1000,
    refetchOnWindowFocus: false,
    retry: 1,
  });

  const specs = query.data ?? EMPTY;
  const getSpec = useCallback(
    (symbol: string | null | undefined): InstrumentSpec | null =>
      symbol ? specs.get(symbol.trim().toUpperCase()) ?? null : null,
    [specs],
  );

  return { getSpec, specs, isLoading: query.isLoading, isError: query.isError };
}
