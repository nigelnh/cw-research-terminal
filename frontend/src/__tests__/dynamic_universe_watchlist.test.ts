import { describe, expect, it } from "vitest";
import type { WatchlistItem } from "../domain/models";
import { isManagedProductDefault } from "../data/watchlist/use_watchlist";

function fullUniverse(): WatchlistItem[] {
  return [
    ...Array.from({ length: 30 }, (_, index) => ({
      symbol: `S${index}`,
      instrumentType: "STOCK" as const,
      addedAt: index,
    })),
    ...Array.from({ length: 319 }, (_, index) => ({
      symbol: `CXXX${String(index).padStart(4, "0")}`,
      instrumentType: "CW" as const,
      underlyingSymbol: "S0",
      addedAt: index + 30,
    })),
  ];
}

describe("dynamic product universe classification", () => {
  it("recognizes a full VN30/CW universe so a new listing can refresh it", () => {
    expect(isManagedProductDefault(fullUniverse(), "anonymous")).toBe(true);
  });

  it("preserves an ordinary customized watchlist", () => {
    const custom: WatchlistItem[] = [
      { symbol: "HPG", instrumentType: "STOCK", addedAt: 1 },
      { symbol: "CHPG2625", instrumentType: "CW", underlyingSymbol: "HPG", addedAt: 2 },
    ];
    expect(isManagedProductDefault(custom, "anonymous")).toBe(false);
  });
});
