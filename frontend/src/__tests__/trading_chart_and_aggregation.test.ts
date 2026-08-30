import { describe, it, expect } from "vitest";
import type { HistoricalBar, MarketQuote, UnderlyingClosePoint } from "@/domain/models";
import {
  aggregateDailyToWeekly,
  aggregateDailyToMonthly,
  aggregateIntradayBars,
} from "@/domain/historical/aggregation";
import { mergeCompletedBarsWithLiveQuote } from "@/domain/historical/current_bar_builder";
import {
  calculateEMA,
  calculateVWAP,
  calculateNormalizedRelative,
} from "@/domain/historical/technical_overlays";
import {
  RANGE_INTERVAL_COMPATIBILITY,
  VENDOR_NATIVE_INTERVALS,
} from "@/domain/historical/types";

describe("Historical OHLCV Local Aggregation Engine", () => {
  const sampleDailyBars: HistoricalBar[] = [
    // Week 1 (Monday to Friday: 2026-08-03 to 2026-08-07)
    { symbol: "HPG", date: "2026-08-03", open: 21000, high: 21500, low: 20800, close: 21400, volume: 1000000 },
    { symbol: "HPG", date: "2026-08-04", open: 21400, high: 21800, low: 21300, close: 21600, volume: 1200000 },
    { symbol: "HPG", date: "2026-08-05", open: 21600, high: 22000, low: 21500, close: 21900, volume: 1500000 },
    { symbol: "HPG", date: "2026-08-06", open: 21900, high: 22100, low: 21700, close: 21800, volume: 800000 },
    { symbol: "HPG", date: "2026-08-07", open: 21800, high: 22200, low: 21750, close: 22100, volume: 1100000 },
    // Week 2 (Monday to Wednesday: 2026-08-10 to 2026-08-12)
    { symbol: "HPG", date: "2026-08-10", open: 22100, high: 22400, low: 22000, close: 22300, volume: 1300000 },
    { symbol: "HPG", date: "2026-08-11", open: 22300, high: 22500, low: 22100, close: 22200, volume: 900000 },
    { symbol: "HPG", date: "2026-08-12", open: 22200, high: 22600, low: 22150, close: 22500, volume: 1400000 },
  ];

  it("1. Aggregates daily bars to weekly (1W) bars correctly without price averaging", () => {
    const weekly = aggregateDailyToWeekly(sampleDailyBars);
    expect(weekly.length).toBe(2);

    // Week 1 verification
    const w1 = weekly[0];
    expect(w1.symbol).toBe("HPG");
    expect(w1.date).toBe("2026-08-03"); // First trading day
    expect(w1.open).toBe(21000);        // Monday open
    expect(w1.high).toBe(22200);        // Max of week
    expect(w1.low).toBe(20800);         // Min of week
    expect(w1.close).toBe(22100);       // Friday close
    expect(w1.volume).toBe(5600000);    // 1.0M + 1.2M + 1.5M + 0.8M + 1.1M

    // Week 2 verification
    const w2 = weekly[1];
    expect(w2.open).toBe(22100);
    expect(w2.high).toBe(22600);
    expect(w2.low).toBe(22000);
    expect(w2.close).toBe(22500);
    expect(w2.volume).toBe(3600000);
  });

  it("2. Aggregates daily bars to monthly (1M) bars correctly", () => {
    const monthly = aggregateDailyToMonthly(sampleDailyBars);
    expect(monthly.length).toBe(1);

    const m = monthly[0];
    expect(m.date).toBe("2026-08-03");
    expect(m.open).toBe(21000);
    expect(m.high).toBe(22600);
    expect(m.low).toBe(20800);
    expect(m.close).toBe(22500);
    expect(m.volume).toBe(9200000);
  });

  it("3. Coarsens intraday 5m bars into 15m intervals", () => {
    const sample5mBars: HistoricalBar[] = [
      { symbol: "HPG", date: "2026-08-26 09:00:00", open: 21800, high: 21900, low: 21750, close: 21850, volume: 50000 },
      { symbol: "HPG", date: "2026-08-26 09:05:00", open: 21850, high: 22000, low: 21800, close: 21950, volume: 80000 },
      { symbol: "HPG", date: "2026-08-26 09:10:00", open: 21950, high: 22050, low: 21900, close: 22000, volume: 60000 },
      // Next 15m bucket
      { symbol: "HPG", date: "2026-08-26 09:15:00", open: 22000, high: 22100, low: 21950, close: 22050, volume: 70000 },
    ];

    const coarsened15m = aggregateIntradayBars(sample5mBars, 15);
    expect(coarsened15m.length).toBe(2);

    const bucket1 = coarsened15m[0];
    expect(bucket1.open).toBe(21800);
    expect(bucket1.high).toBe(22050);
    expect(bucket1.low).toBe(21750);
    expect(bucket1.close).toBe(22000);
    expect(bucket1.volume).toBe(190000); // 50k + 80k + 60k
  });
});

describe("Current Bar Builder & Realtime Merge", () => {
  const completedBars: HistoricalBar[] = [
    { symbol: "HPG", date: "2026-08-25", open: 21500, high: 21800, low: 21400, close: 21700, volume: 5000000 },
  ];

  it("1. Merges live quote into active candle when matching trade exists", () => {
    const liveQuote = {
      symbol: "HPG",
      lastPrice: 22050,
      openPrice: 21800,
      highPrice: 22100,
      lowPrice: 21750,
      totalVolume: 11200000,
      referencePrice: 21700,
      priceChange: 350,
      priceChangePercent: 0.0161,
      bidPrice: 22000,
      askPrice: 22050,
    } as unknown as MarketQuote;

    const merged = mergeCompletedBarsWithLiveQuote(completedBars, liveQuote, "1D", new Date("2026-08-26T14:30:00Z").getTime());
    expect(merged.length).toBe(2);

    const liveBar = merged[1];
    expect(liveBar.symbol).toBe("HPG");
    expect(liveBar.open).toBe(21800);
    expect(liveBar.high).toBe(22100);
    expect(liveBar.low).toBe(21750);
    expect(liveBar.close).toBe(22050);
    expect(liveBar.volume).toBe(11200000);
  });

  it("1b. Returns completed bars UNCHANGED when there is no live quote (market closed)", () => {
    // The instrument panel passes liveQuote only while the session is active; outside a
    // session the chart must show exactly the persisted daily bars — no synthetic
    // "today" candle fabricated from a last-session snapshot price.
    const closedNull = mergeCompletedBarsWithLiveQuote(completedBars, null, "1D");
    expect(closedNull).toBe(completedBars);

    const closedUndef = mergeCompletedBarsWithLiveQuote(completedBars, undefined, "1D");
    expect(closedUndef).toBe(completedBars);

    // A quote object with no matched trade price is likewise ignored.
    const noTrade = { symbol: "HPG", lastPrice: null } as unknown as MarketQuote;
    expect(mergeCompletedBarsWithLiveQuote(completedBars, noTrade, "1D")).toBe(completedBars);
  });

  it("2. Does NOT fabricate CW trade candle when CW only has Bid/Ask and no Last trade", () => {
    const cwQuoteNoTrade = {
      symbol: "CHPG2541",
      lastPrice: null, // No matched trade!
      referencePrice: 300,
      bidPrice: 290,
      askPrice: 300,
      totalVolume: 0,
      priceChange: 0,
      priceChangePercent: 0,
    } as unknown as MarketQuote;

    const emptyHistory: HistoricalBar[] = [];
    const merged = mergeCompletedBarsWithLiveQuote(emptyHistory, cwQuoteNoTrade, "1D");

    // Zero-fabrication invariant: must remain empty!
    expect(merged.length).toBe(0);
  });
});

describe("Technical Overlays & Normalized Relative Calculations", () => {
  it("1. Calculates Exponential Moving Average (EMA 20)", () => {
    const bars: HistoricalBar[] = Array.from({ length: 30 }, (_, i) => ({
      symbol: "HPG",
      date: `2026-07-${String(i + 1).padStart(2, "0")}`,
      open: 20000 + i * 100,
      high: 20200 + i * 100,
      low: 19900 + i * 100,
      close: 20100 + i * 100,
      volume: 1000000,
    }));

    const ema20 = calculateEMA(bars, 20);
    expect(ema20.length).toBe(11); // 30 - 20 + 1 = 11 points
    expect(ema20[0].value).toBeCloseTo(21050, 0);
  });

  it("2. Calculates Volume Weighted Average Price (VWAP)", () => {
    const bars: HistoricalBar[] = [
      { symbol: "HPG", date: "09:00", open: 20000, high: 20200, low: 19800, close: 20000, volume: 1000 },
      { symbol: "HPG", date: "09:05", open: 20000, high: 20400, low: 20000, close: 20200, volume: 2000 },
    ];

    // Bar 1 Typical Price = (20200 + 19800 + 20000) / 3 = 20000. TP * Vol = 20,000,000. CumVol = 1000. VWAP = 20000.
    // Bar 2 Typical Price = (20400 + 20000 + 20200) / 3 = 20200. TP * Vol = 40,400,000. CumTPV = 60,400,000. CumVol = 3000. VWAP = 20133.33.
    const vwap = calculateVWAP(bars);
    expect(vwap.length).toBe(2);
    expect(vwap[0].value).toBe(20000);
    expect(vwap[1].value).toBeCloseTo(20133.33, 1);
  });

  it("3. Calculates Normalized Relative Performance (Base 100)", () => {
    const cwBars: HistoricalBar[] = [
      { symbol: "CVHM2615", date: "2026-08-01", open: 1000, high: 1000, low: 1000, close: 1000, volume: 100 },
      { symbol: "CVHM2615", date: "2026-08-02", open: 1200, high: 1200, low: 1200, close: 1200, volume: 100 },
    ];

    const undBars: UnderlyingClosePoint[] = [
      { symbol: "VHM", date: "2026-08-01", close: 50000, rawClose: 50000 },
      { symbol: "VHM", date: "2026-08-02", close: 55000, rawClose: 55000 },
    ];

    const rel = calculateNormalizedRelative(cwBars, undBars);
    expect(rel.length).toBe(2);

    // Day 1: Both Base 100
    expect(rel[0].cw).toBe(100);
    expect(rel[0].underlying).toBe(100);

    // Day 2: CW rose 20% -> 120; VHM rose 10% -> 110
    expect(rel[1].cw).toBeCloseTo(120, 2);
    expect(rel[1].underlying).toBeCloseTo(110, 2);
  });
});

describe("Range / Interval Compatibility & Vendor Contracts", () => {
  it("1. Enforces Range / Interval compatibility matrix", () => {
    expect(RANGE_INTERVAL_COMPATIBILITY["1D"]).toEqual(["1m", "5m", "15m"]);
    expect(RANGE_INTERVAL_COMPATIBILITY["5D"]).toEqual(["5m", "15m", "30m", "1h"]);
    expect(RANGE_INTERVAL_COMPATIBILITY["1M"]).toEqual(["15m", "30m", "1h", "1D"]);
    expect(RANGE_INTERVAL_COMPATIBILITY["1Y"]).toEqual(["1D", "1W", "1M"]);
  });

  it("2. Distinguishes Vendor-Native vs Project-Derived intervals", () => {
    expect(VENDOR_NATIVE_INTERVALS.has("5m")).toBe(true);
    expect(VENDOR_NATIVE_INTERVALS.has("1D")).toBe(true);
    expect(VENDOR_NATIVE_INTERVALS.has("1W")).toBe(false); // Derived locally
    expect(VENDOR_NATIVE_INTERVALS.has("1M")).toBe(false); // Derived locally
  });
});
