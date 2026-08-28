// @vitest-environment happy-dom
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// The historical query path resolves its BackendClient from this module. Mock the
// singleton so no real network is attempted and calls can be counted.
const getMarketHistory = vi.fn<
  (symbol: string, timeframe?: string, from?: string, to?: string, adjusted?: boolean, signal?: AbortSignal) => Promise<any[]>
>();
vi.mock("@/data/backend/backend_client", () => ({
  BackendClient: class {},
  backendClient: {
    get getMarketHistory() {
      return getMarketHistory;
    },
  },
}));

import { fetchHistoricalBars, sliceBars, resolveDataset } from "@/data/query/historical_bars";
import { queryKeys } from "@/data/query/query_keys";
import { useHistoricalBars } from "@/data/query/use_historical_bars";

function daily(dateStr: string, close: number) {
  return { date: dateStr, open: close, high: close, low: close, close, volume: 1_000, adjusted: true };
}

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity, staleTime: 5 * 60_000 } },
  });
}

function providerFor(qc: QueryClient) {
  return ({ children }: { children: ReactNode }) => createElement(QueryClientProvider, { client: qc }, children);
}

beforeEach(() => {
  getMarketHistory.mockReset();
  getMarketHistory.mockResolvedValue([daily("2026-08-27", 22_250), daily("2026-08-26", 21_800)]);
});

describe("Historical data shaping (pure)", () => {
  it("preserves raw VND close values through the mapper - no scaling, no zeroing", async () => {
    getMarketHistory.mockResolvedValueOnce([daily("2026-08-27", 21_800), daily("2026-08-26", 22_250)]);
    const bars = await fetchHistoricalBars({ symbol: "hpg", timeframe: "3M", adjusted: true, interval: "1D" });
    expect(bars).toHaveLength(2);
    expect(bars.map((b) => Number(b.close)).sort((a, b) => a - b)).toEqual([21_800, 22_250]);
  });

  it("missing history stays an empty array - never fabricated to zero prices", async () => {
    getMarketHistory.mockResolvedValueOnce([]);
    const bars = await fetchHistoricalBars({ symbol: "EMPTY", timeframe: "3M", adjusted: true, interval: "1D" });
    expect(bars).toEqual([]);
  });

  it("threads the AbortSignal through to the backend call", async () => {
    const ctrl = new AbortController();
    await fetchHistoricalBars({ symbol: "HPG", timeframe: "3M", adjusted: true, interval: "1D" }, ctrl.signal);
    expect(getMarketHistory).toHaveBeenCalledWith("HPG", "1D", undefined, undefined, true, ctrl.signal);
  });

  it("resolveDataset maps the UI timeframe to a dataset class + backend timeframe", () => {
    expect(resolveDataset("1D")).toEqual({ dataset: "intraday_1d", backendTimeframe: "5m" });
    expect(resolveDataset("5D")).toEqual({ dataset: "intraday_5d", backendTimeframe: "30m" });
    expect(resolveDataset("3M")).toEqual({ dataset: "daily_1y", backendTimeframe: "1D" });
    expect(resolveDataset("MAX")).toEqual({ dataset: "daily_1y", backendTimeframe: "1D" });
  });

  it("sliceBars trims a full daily dataset to the requested window but keeps 1Y/MAX whole", () => {
    const day = (n: number) => new Date(Date.now() - n * 86_400_000).toISOString().split("T")[0];
    const bars = Array.from({ length: 200 }, (_, i) => ({ symbol: "HPG", ...daily(day(199 - i), 10) }));
    expect(sliceBars(bars, "1M").length).toBeLessThan(bars.length);
    expect(sliceBars(bars, "1Y")).toHaveLength(200);
    expect(sliceBars([], "1M")).toEqual([]);
  });
});

describe("Central query-key factory", () => {
  it("includes every result-changing parameter and is stable / case-insensitive on symbol", () => {
    const base = { symbol: "hpg", timeframe: "3M", interval: "1D", adjusted: true } as const;
    const k = queryKeys.history.bars(base);
    expect(k).toContain("HPG");
    expect(k).toContain("3M");
    expect(k).toContain("adjusted");
    expect(queryKeys.history.bars({ ...base, timeframe: "6M" })).not.toEqual(k);
    expect(queryKeys.history.bars({ ...base, interval: "5m" })).not.toEqual(k);
    expect(queryKeys.history.bars({ ...base, adjusted: false })).not.toEqual(k);
    expect(queryKeys.history.bars({ ...base, symbol: "VHM" })).not.toEqual(k);
    expect(queryKeys.history.bars(base)).toEqual(queryKeys.history.bars({ ...base, symbol: "  HPG " }));
  });
});

describe("useHistoricalBars - TanStack Query ownership", () => {
  it("dedupes concurrent identical requests into one upstream fetch", async () => {
    const qc = makeQueryClient();
    const Wrapper = providerFor(qc);
    const args = { symbol: "HPG", timeframe: "3M", interval: "1D" } as const;
    const a = renderHook(() => useHistoricalBars(args), { wrapper: Wrapper });
    renderHook(() => useHistoricalBars(args), { wrapper: Wrapper });
    renderHook(() => useHistoricalBars(args), { wrapper: Wrapper });
    await waitFor(() => expect(a.result.current.isLoading).toBe(false));
    expect(getMarketHistory).toHaveBeenCalledTimes(1);
    expect(a.result.current.bars.length).toBeGreaterThan(0);
  });

  it("reuses the cache on re-mount within staleTime - no refetch when the drawer reopens", async () => {
    const qc = makeQueryClient();
    const Wrapper = providerFor(qc);
    const args = { symbol: "HPG", timeframe: "3M", interval: "1D" } as const;
    const first = renderHook(() => useHistoricalBars(args), { wrapper: Wrapper });
    await waitFor(() => expect(first.result.current.isLoading).toBe(false));
    first.unmount();
    const second = renderHook(() => useHistoricalBars(args), { wrapper: Wrapper });
    await waitFor(() => expect(second.result.current.bars.length).toBeGreaterThan(0));
    expect(getMarketHistory).toHaveBeenCalledTimes(1);
  });

  it("changing timeframe produces a distinct cache entry and a new fetch", async () => {
    const qc = makeQueryClient();
    const Wrapper = providerFor(qc);
    const h = renderHook(({ tf }: { tf: string }) => useHistoricalBars({ symbol: "HPG", timeframe: tf, interval: "1D" }), {
      wrapper: Wrapper,
      initialProps: { tf: "3M" },
    });
    await waitFor(() => expect(h.result.current.isLoading).toBe(false));
    h.rerender({ tf: "6M" });
    await waitFor(() => expect(h.result.current.isFetching).toBe(false));
    expect(getMarketHistory).toHaveBeenCalledTimes(2);
    const tokens = qc.getQueryCache().getAll().flatMap((q) => q.queryKey as readonly unknown[]);
    expect(tokens).toContain("3M");
    expect(tokens).toContain("6M");
  });

  it("fast symbol switching cannot show stale history - the final key owns the view", async () => {
    getMarketHistory.mockImplementation(async (symbol: string) => {
      await new Promise((r) => setTimeout(r, symbol === "HPG" ? 5 : 40));
      return [daily("2026-08-27", symbol === "HPG" ? 100 : 999)];
    });
    const qc = makeQueryClient();
    const Wrapper = providerFor(qc);
    const h = renderHook(({ s }: { s: string }) => useHistoricalBars({ symbol: s, timeframe: "3M", interval: "1D" }), {
      wrapper: Wrapper,
      initialProps: { s: "HPG" },
    });
    h.rerender({ s: "VHM" });
    h.rerender({ s: "TCB" });
    h.rerender({ s: "HPG" });
    await waitFor(() => expect(h.result.current.bars.length).toBeGreaterThan(0));
    // settled on HPG - a late VHM/TCB response must not have overwritten it
    expect(h.result.current.bars[0].close).toBe(100);
  });

  it("disabled query issues no request and reports not-loading with empty bars", () => {
    const qc = makeQueryClient();
    const h = renderHook(() => useHistoricalBars({ symbol: "HPG", timeframe: "3M", interval: "1D", enabled: false }), {
      wrapper: providerFor(qc),
    });
    expect(h.result.current.isLoading).toBe(false);
    expect(h.result.current.bars).toEqual([]);
    expect(getMarketHistory).not.toHaveBeenCalled();
  });

  it("empty / null symbol never triggers a fetch", () => {
    const qc = makeQueryClient();
    renderHook(() => useHistoricalBars({ symbol: null, timeframe: "3M", interval: "1D" }), { wrapper: providerFor(qc) });
    expect(getMarketHistory).not.toHaveBeenCalled();
  });

  it("distinguishes a legitimate empty range (isEmpty) from an error (isError)", async () => {
    getMarketHistory.mockResolvedValue([]);
    const qc = makeQueryClient();
    const empty = renderHook(() => useHistoricalBars({ symbol: "HPG", timeframe: "3M", interval: "1D" }), {
      wrapper: providerFor(qc),
    });
    await waitFor(() => expect(empty.result.current.isEmpty).toBe(true));
    expect(empty.result.current.isError).toBe(false);
    expect(empty.result.current.bars).toEqual([]);

    getMarketHistory.mockRejectedValue(new Error("HTTP 500 on /api/market/history/HPG: boom"));
    const qc2 = makeQueryClient();
    const errored = renderHook(() => useHistoricalBars({ symbol: "XYZ", timeframe: "3M", interval: "1D" }), {
      wrapper: providerFor(qc2),
    });
    await waitFor(() => expect(errored.result.current.isError).toBe(true));
    expect(errored.result.current.isEmpty).toBe(false);
  });
});
