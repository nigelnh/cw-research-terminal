// @vitest-environment happy-dom
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { PropsWithChildren } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const fixture = vi.hoisted(() => ({
  getDashboardRows: vi.fn(),
  getDashboardAnalytics: vi.fn(),
}));

vi.mock("@/data/backend/backend_client", () => ({
  backendClient: fixture,
}));

vi.mock("@/data/use_research_market", () => ({
  useResearchMarket: () => ({
    quotes: new Map(),
    marketSessionActive: false,
    isRealtimeTracked: () => true,
  }),
}));

import { useDashboardData } from "@/data/query/use_dashboard_data";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

describe("dashboard reload hydration", () => {
  beforeEach(() => {
    fixture.getDashboardRows.mockReset();
    fixture.getDashboardAnalytics.mockReset();
  });

  it("renders the quote response without waiting for analytics", async () => {
    const quote = deferred<any>();
    const analytics = deferred<any>();
    fixture.getDashboardRows.mockReturnValue(quote.promise);
    fixture.getDashboardAnalytics.mockReturnValue(analytics.promise);
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const wrapper = ({ children }: PropsWithChildren) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );

    const { result } = renderHook(() => useDashboardData(["CHPG2617"]), { wrapper });

    await act(async () => {
      quote.resolve({
        rows: [{
          Symbol: "CHPG2617",
          InstrumentType: "CW",
          Traded: 0.44,
          Ref: 0.49,
          provenance: {
            quote: { state: "LAST_SESSION", source: "SNAPSHOT_FINAL" },
            book: { state: "LAST_SESSION", source: "SNAPSHOT_FINAL" },
            reference: { state: "LAST_SESSION", source: "SNAPSHOT_FINAL" },
          },
          displayState: "LAST_SESSION",
          tracked_realtime: true,
        }],
        as_of: "2026-09-04T07:00:00+07:00",
        market_session: "CLOSED_PRE_OPEN",
        market_session_active: false,
        latest_completed_session: "2026-09-03",
        calendar_confidence: "CONFIRMED",
      });
      await quote.promise;
    });

    await waitFor(() => expect(result.current.getRow("CHPG2617")?.quote.lastPrice).toBe(440));
    expect(result.current.getRow("CHPG2617")?.analytics).toBeNull();

    await act(async () => {
      analytics.resolve({
        rows: [{
          Symbol: "CHPG2617",
          analytics: { ivTrade: 0.42, dte: 31 },
          provenance: { state: "LAST_SESSION", source: "QUANT_EOD" },
        }],
        as_of: "2026-09-04T07:00:02+07:00",
        market_session: "CLOSED_PRE_OPEN",
        market_session_active: false,
        latest_completed_session: "2026-09-03",
      });
      await analytics.promise;
    });

    await waitFor(() => expect(result.current.getRow("CHPG2617")?.analytics).toEqual({
      ivTrade: 0.42,
      dte: 31,
    }));
  });
});
