import { describe, it, expect } from "vitest";
import {
  fmtSigned,
  fmtPrice,
  maturityDays,
  dteDisplay,
} from "@/components/common/grid_table";
import { mapRawSnapshotToQuote } from "@/data/backend/mappers/map_snapshot";
import { applyRawPatchToQuote } from "@/data/backend/mappers/map_patch";
import { quoteTimestamp, formatAsOf } from "@/domain/temporal";
import { isQuoteTimestampEligible } from "@/data/query/use_dashboard_data";

import { mergeCompletedBarsWithLiveQuote } from "@/domain/historical/current_bar_builder";

describe("UX data invariants", () => {
  it("retains change direction and index precision, including zero/missing values", () => {
    expect(fmtSigned(350)).toBe("+350");
    expect(fmtSigned(-350)).toBe("−350");
    expect(fmtSigned(-2.37, "INDEX")).toBe("−2.37");
    expect(fmtPrice(1682.47, "INDEX")).toBe("1,682.47");
    expect(fmtSigned(null)).toBe("—");
    expect(fmtSigned(0)).toBe("0");
  });
  it("snapshot, patch and fallback index prices never become VND", () => {
    const q = mapRawSnapshotToQuote({
      Symbol: "VNINDEX",
      InstrumentType: "INDEX",
      Traded: 1682.47,
      Ref: 1684.84,
      change: -2.37,
    });
    expect(q.lastPrice).toBe(1682.47);
    expect(q.priceChange).toBe(-2.37);
    expect(
      applyRawPatchToQuote(q, "VNINDEX", { Traded: 1683.15 }).lastPrice,
    ).toBe(1683.15);
    expect(
      mapRawSnapshotToQuote({
        Symbol: "HPG",
        InstrumentType: "STOCK",
        Traded: 1.2,
      }).lastPrice,
    ).toBe(1200);
    expect(
      mapRawSnapshotToQuote({
        Symbol: "NEWINDEX",
        InstrumentType: "INDEX",
        Traded: 1.2,
      }).lastPrice,
    ).toBe(1.2);
    expect(
      mapRawSnapshotToQuote({ Symbol: "HPG", Traded: null }).lastPrice,
    ).toBeNull();
  });
  it("maturity DTE crosses the ICT midnight boundary and ignores last trading/model DTE", () => {
    expect(maturityDays("2026-09-25", new Date("2026-09-01T16:59:59Z"))).toBe(
      24,
    );
    expect(maturityDays("2026-09-25", new Date("2026-09-01T17:00:00Z"))).toBe(
      23,
    );
    expect(dteDisplay("2099-01-01", null, 500)).toBe("—");
    expect(maturityDays(null)).toBeNull();
  });
  it("never invents AS OF timestamps; session dates stay dates", () => {
    expect(quoteTimestamp({ sourceTimestamp: null })).toBeNull();
    expect(formatAsOf(null)).toBe("Time unavailable");
    expect(formatAsOf("2026-09-01")).not.toContain("15:00");
    const stamp = "2026-09-01T07:45:00.000Z";
    expect(quoteTimestamp({ sourceTimestamp: Date.parse(stamp) })).toBe(stamp);
    expect(isQuoteTimestampEligible(null)).toBe(false);
    expect(isQuoteTimestampEligible(stamp, Date.parse(stamp) + 86401_000)).toBe(
      false,
    );
    expect(isQuoteTimestampEligible(stamp, Date.parse(stamp) + 30_000)).toBe(
      true,
    );
  });
  it("cached quotes cannot fabricate a candle dated today", () => {
    const bars = [
      {
        symbol: "HPG",
        date: "2026-09-01",
        open: 29500,
        high: 30000,
        low: 29000,
        close: 29600,
        volume: 100,
      },
    ];
    const q = mapRawSnapshotToQuote({
      Symbol: "HPG",
      Traded: 29.5,
      ExchangeTime: Date.parse("2026-09-01T07:45:00Z"),
    });
    const merged = mergeCompletedBarsWithLiveQuote(bars, q);
    expect(merged).toHaveLength(1);
    expect(merged[0].date).toBe("2026-09-01");
    expect(
      mergeCompletedBarsWithLiveQuote([], {
        ...q,
        exchangeTimestamp: null,
        sourceTimestamp: null,
      }),
    ).toEqual([]);
  });
});
