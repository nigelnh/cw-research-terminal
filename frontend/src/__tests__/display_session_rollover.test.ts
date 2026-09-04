import { describe, expect, it } from "vitest";
import { mapRawSnapshotToQuote } from "@/data/backend/mappers/map_snapshot";
import { resolveDashboardQuote } from "@/data/query/resolve_dashboard_quote";
import { quoteCell, type QuoteTableValues } from "@/components/common/quote_columns";
import { MARKET_COLOR, priceColor } from "@/components/common/grid_table";
import type { RowProvenance } from "@/domain/temporal";

const at = (time: string) => Date.parse(`2026-09-04T${time}+07:00`);
const snapshot = mapRawSnapshotToQuote({ Symbol: "HPG", Traded: 21.6, Ref: 22,
  Ceil: 23.5, Floor: 20.5, Total_Vol: 27036617, change: -0.4 });
const source: RowProvenance = {
  quote: { state: "LAST_SESSION", source: "SNAPSHOT_FINAL", sessionDate: "2026-09-03" },
  book: { state: "LAST_SESSION", source: "SNAPSHOT_FINAL", sessionDate: "2026-09-03" },
  reference: { state: "LAST_SESSION", source: "SNAPSHOT_FINAL", sessionDate: "2026-09-03" },
};
const current = (fields = {}) => mapRawSnapshotToQuote({ Symbol: "HPG",
  _market_session_date: "2026-09-04", _reference_session_date: "2026-09-04",
  Ref: 21.6, Ceil: 23.1, Floor: 20.1, ...fields });

describe("display session merge", () => {
  it("keeps the closing snapshot before the next display session", () => {
    const result = resolveDashboardQuote(snapshot, undefined, source, false, at("07:59:59"));
    expect(result.quote.lastPrice).toBe(21600);
    expect(result.displayState).toBe("LAST_SESSION");
  });
  it("rollover clears trade/book while showing new reference, without fake zeroes", () => {
    const result = resolveDashboardQuote(snapshot, current(), source, false, at("08:00:01"));
    expect(result.quote.lastPrice).toBeNull();
    expect(result.quote.totalVolume).toBeNull();
    expect(result.quote.priceChange).toBeNull();
    expect(result.quote.referencePrice).toBe(21600);
    expect(result.displayState).toBe("UNAVAILABLE");
  });
  it("ATO book cannot make yesterday's trade live", () => {
    const result = resolveDashboardQuote(snapshot, current({ Bid1_Prc: 21.65,
      _ts_book: at("09:00:00") }), source, true, at("09:00:01"));
    expect(result.quote.lastPrice).toBeNull();
    expect(result.quote.bidPrice).toBe(21650);
    expect(result.provenance.quote.state).toBe("UNAVAILABLE");
    expect(result.provenance.book.state).toBe("LIVE");
  });
  it.each(["11:30:00", "15:00:00", "23:59:59"])("keeps the latest observed trade at %s, not the initial REST value", time => {
    const result = resolveDashboardQuote(snapshot, current({ Traded: 21.8, Total_Vol: 5000,
      _ts_trade: at("11:29:00") }), source, false, at(time));
    expect(result.quote.lastPrice).toBe(21800);
    expect(result.quote.totalVolume).toBe(5000);
    expect(result.provenance.quote.state).toBe(time.startsWith("11:") ? "SESSION_SNAPSHOT" : "LAST_SESSION");
  });
  it("a stale trade stays visible and stale, rather than reverting to yesterday", () => {
    const result = resolveDashboardQuote(snapshot, current({ Traded: 21.8,
      _ts_trade: at("09:15:00") }), source, true, at("09:20:00"));
    expect(result.quote.lastPrice).toBe(21800);
    expect(result.provenance.quote).toMatchObject({ state: "SESSION_SNAPSHOT", stale: true });
  });
  it("an older WS observation cannot overwrite a newer REST group in another UTC offset", () => {
    const newer = { ...source, quote: { ...source.quote, sessionDate: "2026-09-04", asOf: "2026-09-04T09:16:00+07:00" } };
    const result = resolveDashboardQuote(snapshot, current({ Traded: 21.8,
      _ts_trade: at("09:15:00") }), newer, true, at("09:17:00"));
    expect(result.quote.lastPrice).toBe(21600);
  });
});

describe("stock and CW symbol colors", () => {
  it.each(["HPG", "CHPG2617"])("colors %s like its last price across all five states", symbol => {
    for (const [last, expected] of [[150, MARKET_COLOR.ceiling], [110, MARKET_COLOR.up],
      [100, MARKET_COLOR.flat], [90, MARKET_COLOR.down], [50, MARKET_COLOR.floor],
      [null, MARKET_COLOR.null]] as const) {
      const row = { symbol, last, ref: 100, ceiling: 150, floor: 50 } as QuoteTableValues;
      expect(quoteCell(row, "symbol").color).toBe(expected);
      expect(quoteCell(row, "last").color).toBe(expected);
    }
  });
  it("does not infer CW ceiling/floor from ±7%", () => {
    expect(priceColor(120, { ref: 100, ceiling: null, floor: null })).toBe(MARKET_COLOR.up);
    expect(priceColor(80, { ref: 100, ceiling: null, floor: null })).toBe(MARKET_COLOR.down);
  });
  it("does not reconstruct an explicitly unavailable change from mixed-session prices", () => {
    expect(quoteCell({ last: 21650, ref: 21600, change: null } as QuoteTableValues, "change").text).toBe("—");
  });
});
