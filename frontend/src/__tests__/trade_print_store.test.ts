// @vitest-environment happy-dom
/**
 * Live time & sales over the WebSocket.
 *
 * The tape polled REST every 5s while STATS and the watchlist row updated on every tick,
 * so it ran visibly behind them. A print IS a tick, so it now rides the tick path — for
 * every subscribed symbol, not only whichever panel is open.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { acceptTradePrintMessage, tradePrintStore } from "@/data/backend/trade_print_store";

const print = (ts: number, price: number, volume = 100) => ({
  ts, price, volume,
  time: new Date(ts).toISOString().slice(11, 19),
  change: 150, change_percent: 0.0069, side: "S" as const,
  session_date: "2026-09-07",
});

beforeEach(() => {
  for (const s of ["HPG", "VPB", "CVPB2615"]) tradePrintStore.clear(s);
});

describe("tradePrintStore", () => {
  it("accepts a print and exposes it newest-first", () => {
    acceptTradePrintMessage({ type: "trade_print", symbol: "HPG", print: print(1000, 21_850) });
    acceptTradePrintMessage({ type: "trade_print", symbol: "HPG", print: print(2000, 21_900) });
    expect(tradePrintStore.get("HPG").map(p => p.price)).toEqual([21_900, 21_850]);
  });

  it("keeps every subscribed symbol, not just the open panel", () => {
    acceptTradePrintMessage({ type: "trade_print", symbol: "HPG", print: print(1000, 21_850) });
    acceptTradePrintMessage({ type: "trade_print", symbol: "CVPB2615", print: print(1000, 820) });
    expect(tradePrintStore.get("HPG")).toHaveLength(1);
    expect(tradePrintStore.get("CVPB2615")).toHaveLength(1);
    expect(tradePrintStore.get("VPB")).toHaveLength(0);
  });

  it("ignores a match re-delivered after a reconnect", () => {
    const p = print(1000, 21_850);
    acceptTradePrintMessage({ type: "trade_print", symbol: "HPG", print: p });
    acceptTradePrintMessage({ type: "trade_print", symbol: "HPG", print: { ...p } });
    expect(tradePrintStore.get("HPG")).toHaveLength(1);
  });

  it("keeps two genuine prints at the same instant and price but different size", () => {
    acceptTradePrintMessage({ type: "trade_print", symbol: "HPG", print: print(1000, 21_850, 500) });
    acceptTradePrintMessage({ type: "trade_print", symbol: "HPG", print: print(1000, 21_850, 600) });
    expect(tradePrintStore.get("HPG")).toHaveLength(2);
  });

  it("holds a whole session but is still bounded", () => {
    // The bound matches the server's retention: a long-open tab must not end up showing a
    // SHORTER tape than a freshly-opened one gets from the shared server-side log.
    for (let i = 0; i < 8_060; i++) {
      acceptTradePrintMessage({ type: "trade_print", symbol: "HPG", print: print(i, 21_800 + i) });
    }
    const tape = tradePrintStore.get("HPG");
    expect(tape.length).toBe(8_000);
    expect(tape[0].ts).toBe(8_059); // newest survives, oldest dropped
  });

  it("notifies subscribers so the panel re-renders on a tick", () => {
    const seen = vi.fn();
    const stop = tradePrintStore.subscribe(seen);
    acceptTradePrintMessage({ type: "trade_print", symbol: "HPG", print: print(1000, 21_850) });
    expect(seen).toHaveBeenCalled();
    stop();
  });

  it("drops malformed frames instead of poisoning the tape", () => {
    for (const bad of [null, {}, { symbol: "HPG" }, { symbol: "", print: print(1, 1) },
                       { symbol: "HPG", print: { ts: "x", price: 1 } }]) {
      acceptTradePrintMessage(bad);
    }
    expect(tradePrintStore.get("HPG")).toHaveLength(0);
  });
});
