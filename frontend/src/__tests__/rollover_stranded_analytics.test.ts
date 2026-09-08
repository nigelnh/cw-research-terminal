// @vitest-environment happy-dom
/**
 * After the 08:00 ICT rollover the price row correctly blanks for the new session, but the
 * quant read is a separate endpoint with its own session policy and still answers with the
 * previous session's EOD figures. On 2026-09-08 that produced rows showing IV_BID 42.5%
 * beside an empty BID_PRC - a number derived from prices that were no longer displayed.
 */
import { describe, expect, it } from "vitest";
import { renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";

const rows = { dashboard: [] as any[], analytics: [] as any[] };

vi.mock("@/data/backend/backend_client", () => ({
  backendClient: {
    getDashboardRows: async () => ({ rows: rows.dashboard, market_session: "PRE_OPEN" }),
    getDashboardAnalytics: async () => ({ rows: rows.analytics }),
  },
}));
vi.mock("@/data/use_research_market", () => ({
  useResearchMarket: () => ({
    quotes: new Map(), marketSessionActive: false, marketPhase: "CLOSED",
    isRealtimeTracked: () => false,
  }),
}));

import { vi } from "vitest";
import { useDashboardData } from "@/data/query/use_dashboard_data";

function row(quoteSession: string, values: Record<string, unknown> = {}) {
  return {
    Symbol: "CHPG2617", ...values,
    provenance: {
      quote: { state: "UNAVAILABLE", source: "NONE", sessionDate: quoteSession },
      book: { state: "UNAVAILABLE", source: "NONE", sessionDate: quoteSession },
    },
  };
}
const analyticsRow = (session: string) => ({
  Symbol: "CHPG2617",
  analytics: { ivBid: 0.425187, ivTrade: 0.444546, ivAsk: 0.450964, isAvailable: true },
  provenance: { state: "LAST_SESSION", source: "QUANT_EOD", sessionDate: session },
});

async function firstRow() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client: qc }, children);
  const h = renderHook(() => useDashboardData(["CHPG2617"]), { wrapper });
  await vi.waitFor(() => expect(h.result.current.getRow("CHPG2617")).toBeTruthy());
  await vi.waitFor(() =>
    expect((h.result.current as any).getRow("CHPG2617")).toBeDefined(),
  );
  return () => h.result.current.getRow("CHPG2617");
}

describe("analytics stranded by the 08:00 rollover", () => {
  it("drops IV when the row has rolled past the session the IV was computed from", async () => {
    rows.dashboard = [row("2026-09-08")];       // new session, no prices yet
    rows.analytics = [analyticsRow("2026-09-07")];  // yesterday's EOD quant
    const get = await firstRow();
    await vi.waitFor(() => expect(get()?.analytics).toBeNull());
  });

  it("keeps IV when it belongs to the same session as the row", async () => {
    rows.dashboard = [row("2026-09-07")];
    rows.analytics = [analyticsRow("2026-09-07")];
    const get = await firstRow();
    await vi.waitFor(() => expect(get()?.analytics?.ivBid).toBeCloseTo(0.425187));
  });

  it("keeps IV whenever the row still carries a price it could have come from", async () => {
    // A last-session row showing yesterday's close SHOULD still show yesterday's IV.
    rows.dashboard = [row("2026-09-08", { Traded: 1130, Bid1_Prc: 1120, Ask1_Prc: 1140 })];
    rows.analytics = [analyticsRow("2026-09-07")];
    const get = await firstRow();
    await vi.waitFor(() => expect(get()?.analytics?.ivBid).toBeCloseTo(0.425187));
  });
});
