import { describe, expect, it } from "vitest";
import type { HistoricalBar, MarketQuote } from "@/domain/models";
import { quoteSessionDate, withLiveSessionBar } from "@/domain/historical/live_session_bar";

const ICT = 7 * 60 * 60 * 1000;
/** Epoch ms for an ICT wall-clock time. */
const ict = (iso: string) => Date.parse(`${iso}Z`) - ICT;

const history = (): HistoricalBar[] => [
  { symbol: "HPG", date: "2026-09-28", sessionDate: "2026-09-28", open: 20750, high: 20800, low: 20150, close: 20200, volume: 24_184_800, complete: true },
  // Today as the history endpoint served it: a REALTIME_SESSION snapshot, already stale.
  { symbol: "HPG", date: "2026-09-29", sessionDate: "2026-09-29", open: 20200, high: 20400, low: 20150, close: 20250, volume: 2_740_000, complete: false },
];

const quote = (over: Partial<MarketQuote> = {}): MarketQuote =>
  ({
    symbol: "HPG",
    lastPrice: 20200,
    openPrice: 20200,
    highPrice: 20400,
    lowPrice: 20150,
    totalVolume: 2_900_000,
    marketSessionDate: "2026-09-29",
    tradeTimestamp: ict("2026-09-29T09:36:16"),
    exchangeTimestamp: null,
    sourceTimestamp: null,
    receivedTimestamp: 0,
    ...over,
  }) as MarketQuote;

describe("withLiveSessionBar", () => {
  it("closes today's candle at the live print, not the stale snapshot (the reported case)", () => {
    const out = withLiveSessionBar(history(), quote());
    const today = out[out.length - 1];
    expect(today.close).toBe(20200);
    expect(today.open).toBe(20200);
    expect(today.high).toBe(20400);
    expect(today.low).toBe(20150);
    expect(today.volume).toBe(2_900_000);
    expect(out).toHaveLength(2);
    expect(out[0]).toEqual(history()[0]);
  });

  it("widens the range when a print lands outside it", () => {
    const up = withLiveSessionBar(history(), quote({ lastPrice: 20500, highPrice: 20500 }));
    expect(up[1].high).toBe(20500);
    expect(up[1].close).toBe(20500);

    // Even if the quote's own session high has not caught up with its last print.
    const down = withLiveSessionBar(history(), quote({ lastPrice: 20100, lowPrice: 20150 }));
    expect(down[1].low).toBe(20100);
  });

  it("takes the larger session volume, so a lagging source never rolls the bar back", () => {
    expect(withLiveSessionBar(history(), quote({ totalVolume: 3_000_000 }))[1].volume).toBe(3_000_000);
    expect(withLiveSessionBar(history(), quote({ totalVolume: 1_000 }))[1].volume).toBe(2_740_000);
  });

  it("changes nothing without a matched trade", () => {
    const bars = history();
    expect(withLiveSessionBar(bars, quote({ lastPrice: null }))).toBe(bars);
    expect(withLiveSessionBar(bars, quote({ lastPrice: 0 }))).toBe(bars);
    expect(withLiveSessionBar(bars, null)).toBe(bars);
  });

  it("never lets an earlier session's quote touch the newest bar", () => {
    const bars = history();
    const yesterday = quote({ marketSessionDate: "2026-09-28", lastPrice: 19000 });
    expect(withLiveSessionBar(bars, yesterday)).toBe(bars);
  });

  it("hands back the same array when the quote agrees with the bar", () => {
    const bars = history();
    const agreeing = quote({ lastPrice: 20250, totalVolume: 2_740_000 });
    expect(withLiveSessionBar(bars, agreeing)).toBe(bars);
  });

  it("opens today's bar when history has not caught up, from real session aggregates", () => {
    const bars = history().slice(0, 1); // history still ends yesterday
    const out = withLiveSessionBar(bars, quote());
    expect(out).toHaveLength(2);
    expect(out[1]).toMatchObject({
      date: "2026-09-29", sessionDate: "2026-09-29",
      open: 20200, high: 20400, low: 20150, close: 20200, volume: 2_900_000, complete: false,
    });
  });

  it("does not open a bar from a pre-open reset", () => {
    const bars = history().slice(0, 1);
    const reset = quote({ openPrice: 0, highPrice: 0, lowPrice: 0, totalVolume: 0 });
    expect(withLiveSessionBar(bars, reset)).toBe(bars);
  });

  it("does not open a bar for a new session whose last trade printed in the previous one", () => {
    const bars = history().slice(0, 1);
    const carried = quote({ tradeTimestamp: ict("2026-09-28T14:45:00") });
    expect(withLiveSessionBar(bars, carried)).toBe(bars);
  });
});

describe("quoteSessionDate", () => {
  it("prefers the quote's own session stamp", () => {
    expect(quoteSessionDate(quote())).toBe("2026-09-29");
  });

  it("falls back to the trade's ICT date, not its UTC date", () => {
    // 06:30 ICT on the 29th is still the 28th in UTC.
    const early = quote({ marketSessionDate: null, tradeTimestamp: ict("2026-09-29T06:30:00") });
    expect(new Date(early.tradeTimestamp!).toISOString().slice(0, 10)).toBe("2026-09-28");
    expect(quoteSessionDate(early)).toBe("2026-09-29");
  });

  it("returns null rather than guessing from the browser clock", () => {
    expect(quoteSessionDate(quote({ marketSessionDate: null, tradeTimestamp: null }))).toBeNull();
  });
});
