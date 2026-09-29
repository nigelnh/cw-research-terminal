import { describe, expect, it } from "vitest";
import type { HistoricalBar, MarketQuote } from "@/domain/models";
import {
  aggregateDaily,
  DAY_INTERVALS,
  historyRequestFor,
  INTRADAY_INTERVALS,
  isIntradayInterval,
} from "@/domain/historical/chart_intervals";
import { withLiveSessionBar } from "@/domain/historical/live_session_bar";
import { formatIctTick, formatIctTime } from "@/components/common/trading_chart";

const bar = (date: string, o: number, h: number, l: number, c: number, v = 100): HistoricalBar => ({
  symbol: "HPG", date, sessionDate: date, open: o, high: h, low: l, close: c, volume: v,
});

/** Weekday sessions from `start` for `n` sessions, closes 1, 2, 3... */
function sessions(start: string, n: number): HistoricalBar[] {
  const out: HistoricalBar[] = [];
  const d = new Date(`${start}T00:00:00Z`);
  while (out.length < n) {
    if (d.getUTCDay() !== 0 && d.getUTCDay() !== 6) {
      const k = out.length + 1;
      out.push(bar(d.toISOString().slice(0, 10), k, k + 0.5, k - 0.5, k));
    }
    d.setUTCDate(d.getUTCDate() + 1);
  }
  return out;
}

describe("interval catalogue", () => {
  it("offers the requested intraday and day intervals, in order", () => {
    expect([...INTRADAY_INTERVALS]).toEqual(["1m", "5m", "30m", "1h"]);
    expect([...DAY_INTERVALS]).toEqual(["1D", "5D", "1W", "3W", "1M", "3M", "6M", "1Y"]);
  });

  it("asks the source for intraday granularities directly", () => {
    for (const i of INTRADAY_INTERVALS) {
      expect(isIntradayInterval(i)).toBe(true);
      expect(historyRequestFor(i).interval).toBe(i);
    }
    expect(historyRequestFor("1m").timeframe).toBe("5D");
    expect(historyRequestFor("1h").timeframe).toBe("6M");
  });

  it("builds every day interval from one deep daily series, so switching never refetches", () => {
    for (const i of DAY_INTERVALS) {
      expect(isIntradayInterval(i)).toBe(false);
      expect(historyRequestFor(i)).toEqual({ timeframe: "MAX", interval: "1D" });
    }
  });
});

describe("aggregateDaily", () => {
  it("combines a week: first open, last close, extreme high/low, summed volume", () => {
    const week = [
      bar("2026-09-21", 10, 12, 9, 11, 100),
      bar("2026-09-22", 11, 15, 10, 14, 200),
      bar("2026-09-23", 14, 14, 8, 9, 300),
    ];
    expect(aggregateDaily(week, "1W")).toEqual([
      expect.objectContaining({ date: "2026-09-21", open: 10, high: 15, low: 8, close: 9, volume: 600 }),
    ]);
  });

  it("buckets months, quarters, halves and years on the calendar", () => {
    const bars = [
      bar("2026-01-05", 1, 1, 1, 1), bar("2026-02-02", 2, 2, 2, 2), bar("2026-04-01", 3, 3, 3, 3),
      bar("2026-07-01", 4, 4, 4, 4), bar("2026-12-31", 5, 5, 5, 5), bar("2027-01-04", 6, 6, 6, 6),
    ];
    expect(aggregateDaily(bars, "1M").map((b) => b.date)).toEqual(
      ["2026-01-05", "2026-02-02", "2026-04-01", "2026-07-01", "2026-12-31", "2027-01-04"],
    );
    expect(aggregateDaily(bars, "3M").map((b) => [b.date, b.close])).toEqual([
      ["2026-01-05", 2], ["2026-04-01", 3], ["2026-07-01", 4], ["2026-12-31", 5], ["2027-01-04", 6],
    ]);
    expect(aggregateDaily(bars, "6M").map((b) => [b.date, b.close])).toEqual([
      ["2026-01-05", 3], ["2026-07-01", 5], ["2027-01-04", 6],
    ]);
    expect(aggregateDaily(bars, "1Y").map((b) => [b.date, b.open, b.close])).toEqual([
      ["2026-01-05", 1, 5], ["2027-01-04", 6, 6],
    ]);
  });

  it("makes three-week candles that start on a Monday and hold three weeks", () => {
    const candles = aggregateDaily(sessions("2026-01-05", 60), "3W");
    for (const c of candles) expect(new Date(`${c.date}T00:00:00Z`).getUTCDay()).toBe(1);
    // Only the first and last may be partial; every candle between is 15 sessions x 100.
    expect(candles.length).toBeGreaterThanOrEqual(4);
    expect(candles.slice(1, -1).every((c) => c.volume === 1500)).toBe(true);
  });

  it("makes 5D candles of five sessions each, which a holiday does not shorten", () => {
    const withHoliday = sessions("2026-04-27", 12).filter((b) => b.date !== "2026-04-30"); // 30/4 closed
    const candles = aggregateDaily(withHoliday, "5D");
    expect(candles.map((c) => c.volume)).toEqual([500, 500, 100]);
    expect(candles[0].close).toBe(withHoliday[4].close);
  });

  it("returns daily bars sorted and complete for 1D", () => {
    const shuffled = [bar("2026-09-22", 1, 1, 1, 1), bar("2026-09-21", 2, 2, 2, 2)];
    expect(aggregateDaily(shuffled, "1D").map((b) => b.date)).toEqual(["2026-09-21", "2026-09-22"]);
  });
});

describe("the current long candle follows the tape", () => {
  it("patches today's daily bar before aggregating, so the week closes at the live print", () => {
    const history = [bar("2026-09-28", 20750, 20800, 20150, 20200), bar("2026-09-29", 20200, 20400, 20150, 20250)];
    const quote = {
      symbol: "HPG", lastPrice: 20100, openPrice: 20200, highPrice: 20400, lowPrice: 20100,
      totalVolume: 500, marketSessionDate: "2026-09-29", tradeTimestamp: null,
      exchangeTimestamp: null, sourceTimestamp: null, receivedTimestamp: 0,
    } as unknown as MarketQuote;
    const [week] = aggregateDaily(withLiveSessionBar(history, quote), "1W");
    expect(week.close).toBe(20100);
    expect(week.low).toBe(20100);
  });
});

describe("chart time labels are Vietnam time", () => {
  // 2026-09-29 09:15 ICT = 02:15 UTC. lightweight-charts would have printed 02:15.
  const t = Date.UTC(2026, 8, 29, 2, 15) / 1000;

  it("shows the crosshair time in ICT", () => {
    expect(formatIctTime(t as never, true)).toBe("29 Sep '26 09:15");
    expect(formatIctTime(t as never, false)).toBe("29 Sep '26");
  });

  it("labels axis ticks in ICT", () => {
    expect(formatIctTick(t as never, 3)).toBe("09:15");
    expect(formatIctTick(t as never, 2)).toBe("29");
    expect(formatIctTick(t as never, 1)).toBe("Sep");
    expect(formatIctTick(t as never, 0)).toBe("2026");
  });

  it("keeps a daily bar on its own date", () => {
    const daily = Date.UTC(2026, 8, 29) / 1000; // how the chart times a YYYY-MM-DD bar
    expect(formatIctTime(daily as never, false)).toBe("29 Sep '26");
  });
});
