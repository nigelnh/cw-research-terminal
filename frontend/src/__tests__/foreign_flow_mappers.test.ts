import { describe, expect, it } from "vitest";
import { mapRawSnapshotToQuote } from "@/data/backend/mappers/map_snapshot";
import { applyRawPatchToQuote } from "@/data/backend/mappers/map_patch";
import { resolveDashboardQuote } from "@/data/query/resolve_dashboard_quote";
import type { RowProvenance } from "@/domain/temporal";

const at = (time: string) => Date.parse(`2026-11-13T${time}+07:00`);

describe("foreign buy / sell / room on the wire", () => {
  it("maps the snapshot fields in shares, and a missing one to null", () => {
    const quote = mapRawSnapshotToQuote({ Symbol: "HPG", Foreign_Buy_Vol: 1_633_200,
      Foreign_Sell_Vol: 0, Foreign_Room: 2_292_162_142 });
    expect([quote.foreignBuy, quote.foreignSell, quote.foreignRoom]).toEqual([1_633_200, 0, 2_292_162_142]);
    expect(mapRawSnapshotToQuote({ Symbol: "HPG" }).foreignRoom).toBeNull();
  });

  it("applies a patch and flashes the changed field", () => {
    const base = mapRawSnapshotToQuote({ Symbol: "HPG", Foreign_Buy_Vol: 1_000_000, Foreign_Room: 500 });
    const next = applyRawPatchToQuote(base, "HPG", { Foreign_Buy_Vol: 1_200_000 });
    expect(next.foreignBuy).toBe(1_200_000);
    expect(next.foreignRoom).toBe(500); // a field the patch omits is kept
    expect(next.realtimePulses?.foreignBuy?.direction).toBe("up");
  });

  it("travels with the trade group when the dashboard merges a fresher live quote", () => {
    const rest = mapRawSnapshotToQuote({ Symbol: "HPG", Traded: 21.1, Foreign_Buy_Vol: 1_000_000 });
    const source: RowProvenance = {
      quote: { state: "SESSION_SNAPSHOT", source: "PRICE_BOARD", sessionDate: "2026-11-13", asOf: new Date(at("10:00:00")).toISOString() },
      book: { state: "UNAVAILABLE", source: "NONE", sessionDate: "2026-11-13" },
      reference: { state: "DERIVED", source: "SESSION_REFERENCE", sessionDate: "2026-11-13" },
    };
    const live = mapRawSnapshotToQuote({ Symbol: "HPG", Traded: 21.15, _ts_trade: at("10:00:05"),
      _market_session_date: "2026-11-13", Foreign_Buy_Vol: 1_200_000, Foreign_Room: 2_292_162_142 });
    const { quote } = resolveDashboardQuote(rest, live, source, true, at("10:00:06"));
    expect(quote.foreignBuy).toBe(1_200_000);
    expect(quote.foreignRoom).toBe(2_292_162_142);
  });
});
