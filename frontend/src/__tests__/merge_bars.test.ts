/**
 * Chart bar precedence, and what a merged candle is allowed to claim.
 *
 * Three sources can offer a bar for the same day: ingested history (the exchange's own),
 * the session running right now, and a snapshot of a session this server merely observed.
 * Getting the order wrong either loses a day the terminal displayed or overwrites an
 * authoritative bar with a guess.
 */
import { describe, expect, it } from "vitest";
import { aggregateProvenance, mergeHistoricalBars } from "@/domain/historical/merge_bars";
import type { HistoricalBar } from "@/domain/models";

const bar = (over: Partial<HistoricalBar>): HistoricalBar => ({
  date: "2026-09-07", open: 21800, high: 22150, low: 21550, close: 21550,
  volume: 19957800, sessionDate: "2026-09-07", priceBasis: "RAW",
  source: "FIINQUANT", complete: true, asOf: "2026-09-07T15:00:00+07:00",
  ...over,
} as HistoricalBar);

describe("mergeHistoricalBars", () => {
  it("appends a live bar for a day history does not have", () => {
    const out = mergeHistoricalBars([bar({ date: "2026-09-04", sessionDate: "2026-09-04" })],
      [bar({ source: "REALTIME_SESSION", complete: false })]);
    expect(out.map(b => b.date)).toEqual(["2026-09-04", "2026-09-07"]);
  });

  it("never lets a live bar overwrite a completed one", () => {
    const settled = bar({ close: 21560 });
    const out = mergeHistoricalBars([settled], [bar({ close: 21550, source: "REALTIME_SESSION", complete: false })]);
    expect(out).toEqual([settled]);
  });

  it("does let a live bar replace an observed snapshot of the same day", () => {
    // A snapshot is the last thing written for a session that may still be moving.
    const out = mergeHistoricalBars(
      [bar({ close: 21500, source: "OBSERVED_SESSION", asOf: "2026-09-07T14:30:00+07:00" })],
      [bar({ close: 21550, source: "REALTIME_SESSION", complete: false, asOf: "2026-09-07T14:59:00+07:00" })],
    );
    expect(out[0].close).toBe(21550);
  });

  it("rejects a live bar that is older than what it would replace", () => {
    // A late WebSocket frame must not roll the candle backwards.
    const current = bar({ close: 21550, source: "OBSERVED_SESSION", asOf: "2026-09-07T14:59:00+07:00" });
    const late = bar({ close: 21400, source: "REALTIME_SESSION", complete: false, asOf: "2026-09-07T14:30:00+07:00" });
    expect(mergeHistoricalBars([current], [late])[0].close).toBe(21550);
  });

  it("drops live bars belonging to a different session than the one displayed", () => {
    const out = mergeHistoricalBars([], [bar({ sessionDate: "2026-09-04" })], "2026-09-07");
    expect(out).toEqual([]);
  });

  it("keeps the series in date order", () => {
    const out = mergeHistoricalBars(
      [bar({ date: "2026-09-07" }), bar({ date: "2026-09-03", sessionDate: "2026-09-03" })],
      [bar({ date: "2026-09-04", sessionDate: "2026-09-04", source: "REALTIME_SESSION", complete: false })],
    );
    expect(out.map(b => b.date)).toEqual(["2026-09-03", "2026-09-04", "2026-09-07"]);
  });
});

describe("aggregateProvenance", () => {
  it("reports a single source plainly", () => {
    const p = aggregateProvenance([bar({}), bar({ date: "2026-09-04" })]);
    expect(p.source).toBe("FIINQUANT");
    expect(p.priceBasis).toBe("RAW");
  });

  it("labels a mixed-source aggregate as mixed rather than picking one", () => {
    const p = aggregateProvenance([bar({}), bar({ date: "2026-09-04", source: "OBSERVED_SESSION" })]);
    expect(p.source).toContain("MIXED");
    expect(p.source).toContain("OBSERVED_SESSION");
  });

  it("refuses a single price basis when the bars disagree", () => {
    // A RAW snapshot must never be relabelled ADJUSTED by aggregation.
    const p = aggregateProvenance([bar({}), bar({ date: "2026-09-04", priceBasis: "ADJUSTED" })]);
    expect(p.priceBasis).toBeNull();
  });

  it("is not complete when any bar is an observed session", () => {
    expect(aggregateProvenance([bar({}), bar({ source: "OBSERVED_SESSION" })]).complete).toBe(false);
    expect(aggregateProvenance([bar({}), bar({})]).complete).toBe(true);
  });

  it("carries the newest asOf, not the first", () => {
    const p = aggregateProvenance([
      bar({ asOf: "2026-09-04T15:00:00+07:00" }), bar({ asOf: "2026-09-07T15:00:00+07:00" }),
    ]);
    expect(p.asOf).toBe("2026-09-07T15:00:00+07:00");
  });

  it("only sums value when every bar has one", () => {
    expect(aggregateProvenance([bar({ value: 100 }), bar({ value: 200 })]).value).toBe(300);
    expect(aggregateProvenance([bar({ value: 100 }), bar({ value: null })]).value).toBeNull();
  });
});
