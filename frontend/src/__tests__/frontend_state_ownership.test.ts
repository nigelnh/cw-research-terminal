// @vitest-environment happy-dom
import { describe, it, expect, beforeEach } from "vitest";
import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { renderHook, act, waitFor } from "@testing-library/react";
import { useSearchParam, useNullableSearchParam } from "@/data/url/use_url_state";
import { deriveSelectedInstrument } from "@/data/selected_instrument";
import type { CoveredWarrant, WatchlistItem } from "@/domain/models";

const SRC = resolve(__dirname, "..");

beforeEach(() => {
  window.history.replaceState(null, "", "/");
});

describe("URL state - shareable / navigable view", () => {
  it("round-trips: writing params then re-reading a fresh hook reconstructs the same view", async () => {
    const w = renderHook(() => {
      const [tab, setTab] = useSearchParam("tab", "dashboard");
      const [symbol, setSymbol] = useNullableSearchParam("symbol");
      const [range, setRange] = useSearchParam("range", "1M");
      return { tab, setTab, symbol, setSymbol, range, setRange };
    });

    act(() => {
      w.result.current.setTab("research");
      w.result.current.setSymbol("HPG");
      w.result.current.setRange("6M");
    });

    const qs = window.location.search;
    expect(new URLSearchParams(qs).get("tab")).toBe("research");
    expect(new URLSearchParams(qs).get("symbol")).toBe("HPG");
    expect(new URLSearchParams(qs).get("range")).toBe("6M");

    // "open the copied URL elsewhere" == a brand new component reading the same search
    const fresh = renderHook(() => ({
      tab: useSearchParam("tab", "dashboard")[0],
      symbol: useNullableSearchParam("symbol")[0],
      range: useSearchParam("range", "1M")[0],
    }));
    expect(fresh.result.current).toEqual({ tab: "research", symbol: "HPG", range: "6M" });
  });

  it("a value equal to its default is elided from the URL - canonical shareable links", () => {
    const w = renderHook(() => useSearchParam("tab", "dashboard"));
    act(() => w.result.current[1]("research"));
    expect(window.location.search).toContain("tab=research");
    act(() => w.result.current[1]("dashboard"));
    expect(window.location.search).not.toContain("tab");
  });

  it("reacts to browser back/forward: a popstate that changed the URL re-reads the view", async () => {
    const w = renderHook(() => useNullableSearchParam("symbol"));
    act(() => w.result.current[1]("HPG", "push"));
    act(() => w.result.current[1]("VHM", "push"));
    expect(w.result.current[0]).toBe("VHM");

    // simulate the browser popping the history stack back one entry
    act(() => {
      window.history.replaceState(window.history.state, "", "/?symbol=HPG");
      window.dispatchEvent(new Event("popstate"));
    });
    await waitFor(() => expect(w.result.current[0]).toBe("HPG"));

    // ...and forward again
    act(() => {
      window.history.replaceState(window.history.state, "", "/?symbol=VHM");
      window.dispatchEvent(new Event("popstate"));
    });
    await waitFor(() => expect(w.result.current[0]).toBe("VHM"));
  });

  it("replace mode overwrites the current param value in place", () => {
    const w = renderHook(() => useSearchParam("interval", "1D"));
    act(() => w.result.current[1]("30m", "push"));
    act(() => w.result.current[1]("5m", "replace"));
    expect(w.result.current[0]).toBe("5m");
    expect(window.location.search).toBe("?interval=5m");
  });
});

describe("Selected instrument is derived, never stored", () => {
  const wl: WatchlistItem = {
    symbol: "HPG",
    instrumentType: "STOCK",
    underlyingSymbol: null,
    issuer: null,
    strikePrice: null,
    exerciseRatio: null,
    maturityDate: null,
    lastTradingDate: null,
  } as WatchlistItem;

  it("returns null without a symbol", () => {
    expect(deriveSelectedInstrument(null, {})).toBeNull();
    expect(deriveSelectedInstrument(undefined, {})).toBeNull();
  });

  it("builds metadata from the watchlist item and merges the live quote from the realtime store", () => {
    const quote = { symbol: "HPG", last: 28_500 } as any;
    const view = deriveSelectedInstrument("hpg", { watchlistItem: wl, quote });
    expect(view).toMatchObject({ symbol: "HPG", instrumentType: "STOCK", quote });
  });

  it("falls back to the research-universe record for a CW and infers the CW type", () => {
    const universeCw = {
      symbol: "CVPB2615",
      underlyingSymbol: "VPB",
      issuer: "SSI",
      strikePrice: 20_000,
      exerciseRatio: 5,
    } as CoveredWarrant;
    const view = deriveSelectedInstrument("CVPB2615", { universeCw });
    expect(view).toMatchObject({
      symbol: "CVPB2615",
      instrumentType: "CW",
      underlyingSymbol: "VPB",
      issuer: "SSI",
      strikePrice: 20_000,
    });
  });
});

describe("Single realtime store - no duplicate quote pipelines", () => {
  it("the second WebSocket/worker pipeline has been removed", () => {
    expect(existsSync(resolve(SRC, "data/use_equity_data.tsx"))).toBe(false);
    expect(existsSync(resolve(SRC, "data/ws_worker.ts"))).toBe(false);
    expect(existsSync(resolve(SRC, "data/ws_client.ts"))).toBe(false);
    expect(existsSync(resolve(SRC, "tables"))).toBe(false);
  });

  it("the localStorage historical cache (duplicated server state) has been removed", () => {
    expect(existsSync(resolve(SRC, "data/historical/historical_data_cache.ts"))).toBe(false);
  });

  it("backendWebSocketClient is a single shared instance exposing one subscribe/getRevision store", async () => {
    const mod = await import("@/data/backend/backend_websocket_client");
    const a = mod.backendWebSocketClient;
    const b = (await import("@/data/backend/backend_websocket_client")).backendWebSocketClient;
    expect(a).toBe(b);
    expect(typeof a.subscribe).toBe("function");
    expect(typeof a.getRevision).toBe("function");
  });
});
