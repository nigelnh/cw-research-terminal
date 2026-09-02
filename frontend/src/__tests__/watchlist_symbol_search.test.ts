import { describe, expect, it } from "vitest";
import { matchingSymbols, normalizeSearch, prioritizeWatchlist, type WatchlistSearchOption } from "@/features/watchlist/watchlist_symbol_search";

const options: WatchlistSearchOption[] = [
  { symbol: "HPG", kind: "stock", name: "Hoa Phat Group", exchange: "HOSE", underlying: null },
  { symbol: "CHPG2602", kind: "cw", name: "HPG · TCBS", exchange: "HOSE", underlying: "HPG" },
  { symbol: "VPB", kind: "stock", name: "Vietnam Prosperity Bank", exchange: "HOSE", underlying: null },
  { symbol: "CVPB2615", kind: "cw", name: "VPB · ACBS", exchange: "HOSE", underlying: "VPB" },
];
const rows = options.map(({ symbol, kind, underlying }) => ({ symbol, kind, underlying }));

describe("watchlist symbol search hierarchy", () => {
  it("matches company names without Vietnamese diacritics and lifts the full stock group", () => {
    expect(normalizeSearch("Hòa Phát")).toBe("HOA PHAT");
    const matches = matchingSymbols(options, "Hoa Phat");
    const result = prioritizeWatchlist(rows, matches);
    expect(result.rows.map(row => row.symbol)).toEqual(["HPG", "CHPG2602", "VPB", "CVPB2615"]);
    expect([...result.highlighted]).toEqual(["HPG", "CHPG2602"]);
  });

  it("puts one matching CW first inside its lifted parent group and leaves all other rows visible", () => {
    const matches = matchingSymbols(options, "CVPB2615");
    const result = prioritizeWatchlist(rows, matches);
    expect(result.rows.map(row => row.symbol)).toEqual(["VPB", "CVPB2615", "HPG", "CHPG2602"]);
    expect([...result.highlighted]).toEqual(["CVPB2615"]);
  });
});
