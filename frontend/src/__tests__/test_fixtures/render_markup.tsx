import type { ReactElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

/**
 * SSR-render a component tree that may contain TanStack Query hooks. A fresh, non-retrying,
 * non-fetching QueryClient is provided per call so tests stay isolated. (In react-dom/server
 * effects don't run, so no network is attempted.)
 */
export function renderMarkup(ui: ReactElement): string {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: Infinity } },
  });
  return renderToStaticMarkup(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}
