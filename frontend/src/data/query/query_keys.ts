/**
 * Canonical TanStack Query key factory.
 *
 * Every key includes ALL parameters that change the result. There is exactly ONE key
 * shape per server resource - do not introduce ad-hoc variants
 * (["history", sym] vs ["bars", sym, tf]) elsewhere.
 */

export type HistoryKeyParams = {
  symbol: string;
  timeframe: string; // canonical UI timeframe token (e.g. "3M", "1D")
  interval?: string | null; // resolution the chart renders (e.g. "1D", "5m")
  adjusted: boolean;
  from?: string | null;
  to?: string | null;
};

export const queryKeys = {
  all: ["cw-research"] as const,

  history: {
    all: ["cw-research", "history"] as const,
    bars: (p: HistoryKeyParams) =>
      [
        "cw-research",
        "history",
        p.symbol.trim().toUpperCase(),
        p.timeframe,
        p.interval ?? null,
        p.adjusted ? "adjusted" : "raw",
        p.from ?? null,
        p.to ?? null,
      ] as const,
  },

  instruments: {
    all: ["cw-research", "instruments"] as const,
    activeWarrants: (f?: { issuer?: string | null; underlying?: string | null }) =>
      [
        "cw-research",
        "instruments",
        "active-warrants",
        f?.issuer ?? null,
        f?.underlying ?? null,
      ] as const,
    spec: (symbol: string) =>
      ["cw-research", "instruments", "spec", symbol.trim().toUpperCase()] as const,
  },

  quant: {
    all: ["cw-research", "quant"] as const,
    analytics: (symbol: string) =>
      ["cw-research", "quant", "analytics", symbol.trim().toUpperCase()] as const,
  },
} as const;
