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
  marketOverview: ["cw-research", "market-overview"] as const,
  stockProfiles: (symbols: string[]) => ["cw-research", "stock-profiles", ...symbols] as const,

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
    activeWarrants: (f?: {
      issuer?: string | null;
      underlying?: string | null;
      status?: string;
    }) =>
      [
        "cw-research",
        "instruments",
        "active-warrants",
        f?.issuer ?? null,
        f?.underlying ?? null,
        f?.status ?? "ACTIVE",
      ] as const,
    spec: (symbol: string) =>
      [
        "cw-research",
        "instruments",
        "spec",
        symbol.trim().toUpperCase(),
      ] as const,
  },

  quant: {
    all: ["cw-research", "quant"] as const,
    analytics: (symbol: string) =>
      [
        "cw-research",
        "quant",
        "analytics",
        symbol.trim().toUpperCase(),
      ] as const,
  },

  /** Research enrichment (Step 14A): PostgreSQL-backed news / corporate actions. */
  research: {
    all: ["cw-research", "research"] as const,
    news: (p: { symbol?: string | null; q?: string | null; lang?: string }) =>
      [
        "cw-research",
        "research",
        "news",
        (p.symbol ?? "").trim().toUpperCase() || null,
        (p.q ?? "").trim() || null,
        p.lang ?? "vi",
      ] as const,
    corporateActions: (symbol: string) =>
      [
        "cw-research",
        "research",
        "corporate-actions",
        symbol.trim().toUpperCase(),
      ] as const,
    companyEvents: (symbol: string) =>
      [
        "cw-research",
        "research",
        "company-events",
        symbol.trim().toUpperCase(),
      ] as const,
    feedFacets: ["cw-research", "research", "feed-facets"] as const,
    feed: (p: {
      symbols?: string[] | null;
      dateFrom?: string;
      dateTo?: string;
      pageSize?: number;
      symbol?: string | null;
      source?: string | null;
      contentType?: string | null;
      eventClass?: string | null;
      q?: string | null;
      lang?: string;
    }) =>
      [
        "cw-research",
        "research",
        "feed",
        p.symbols == null ? null : [...p.symbols].sort(),
        p.dateFrom || null,
        p.dateTo || null,
        p.pageSize ?? 40,
        (p.symbol ?? "").trim().toUpperCase() || null,
        p.source ?? null,
        p.contentType ?? null,
        p.eventClass ?? null,
        (p.q ?? "").trim() || null,
        p.lang ?? "vi",
      ] as const,
  },

  /**
   * Per-user server state. EVERY key is scoped by the verified auth subject so nothing
   * survives a user switch: `queryClient.clear()` on identity change wipes it, and even
   * without that a different subject is simply a different cache entry.
   */
  me: {
    root: (subject: string) => ["cw-research", "me", subject] as const,
    watchlist: (subject: string) =>
      ["cw-research", "me", subject, "watchlist"] as const,
  },
} as const;
