import { describe, expect, it } from "vitest";
import { overviewRefetchInterval, type MarketOverviewData } from "@/data/query/use_market_overview";

describe("shared overview polling", () => {
  const data = { market_session_active: true, availability: "PARTIAL" } as MarketOverviewData;
  it("checks before the backend 60-second in-session cache expires", () => {
    expect(overviewRefetchInterval(data)).toBe(15_000);
    expect(overviewRefetchInterval({ ...data, refreshing: true })).toBe(2_000);
    expect(overviewRefetchInterval({ ...data, market_session_active: false })).toBe(60_000);
  });
});
