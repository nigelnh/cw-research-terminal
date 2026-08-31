import type { ReactElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AiChatProvider } from "@/data/ai/ai_chat_provider";

export interface SeedQuery {
  queryKey: unknown[];
  data: unknown;
}

/**
 * SSR-render a component tree that may contain TanStack Query hooks. A fresh, non-retrying,
 * non-fetching QueryClient is provided per call so tests stay isolated. (In react-dom/server
 * effects don't run, so no network is attempted.)
 *
 * Pass `seedQueries` to pre-populate query caches (e.g. the canonical instrument-spec map)
 * so a component that hydrates contract metadata from the backend renders deterministically.
 */
export function renderMarkup(ui: ReactElement, seedQueries: SeedQuery[] = []): string {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: Infinity } },
  });
  for (const q of seedQueries) client.setQueryData(q.queryKey, q.data);
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <AiChatProvider>{ui}</AiChatProvider>
    </QueryClientProvider>,
  );
}

/** Build the seed entry for `useInstrumentSpecs` from an array of partial specs. */
export function seedInstrumentSpecs(specs: Array<Record<string, unknown>>): SeedQuery {
  const m = new Map<string, unknown>();
  for (const s of specs) {
    const base = {
      symbol: "",
      instrumentType: "CW",
      issuer: null,
      underlyingSymbol: null,
      strikePrice: null,
      exerciseRatio: null,
      maturityDate: null,
      lastTradingDate: null,
      status: "ACTIVE",
      dataQuality: null,
      metadataVerification: null,
      ...s,
    };
    m.set(String(base.symbol).toUpperCase(), base);
  }
  return { queryKey: ["instrument-specs", "active"], data: m };
}
