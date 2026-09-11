/**
 * The gate that stops IV describing prices it was not computed from.
 *
 * On 2026-09-08 the board showed IV_BID 42.5% beside an empty BID_PRC: prices and quant
 * come from different endpoints with different session policies, and merging them in the
 * browser produced a row that contradicted itself. This resolver is the single place that
 * decides whether an analytics payload still describes the quote it is being attached to.
 * It had no tests.
 */
import { describe, expect, it } from "vitest";
import { normalizeAnalytics, resolveDashboardAnalytics } from "@/data/query/resolve_dashboard_analytics";
import type { MarketQuote } from "@/domain/models";

const S = "2026-09-07";

const quote = (over: Partial<MarketQuote> = {}): MarketQuote => ({
  symbol: "CHPG2617", lastPrice: 1130, bidPrice: 1120, askPrice: 1140,
  marketSessionDate: S, ...over,
} as MarketQuote);

const analytics = (over: Record<string, any> = {}) => ({
  isAvailable: true, sessionDate: S, calculatedAt: `${S}T15:00:00+07:00`,
  ivBid: 0.42, ivAsk: 0.45, ivTrade: 0.44, ivMid: 0.435,
  delta: 0.1, gamma: 1e-5, theta: -1.9, vega: 15.5, rho: 9.7,
  greeksVolatilitySource: "IV_TRADE",
  modelInputs: { underlying_price: 25000, market_bid: 1120, market_ask: 1140, market_last: 1130 },
  inputProvenance: {
    underlying: { sessionDate: S }, book: { sessionDate: S }, trade: { sessionDate: S },
  },
  ...over,
});

describe("resolveDashboardAnalytics", () => {
  it("passes analytics whose every input matches the quote and session", () => {
    const out = resolveDashboardAnalytics([analytics()], quote(), S);
    expect(out?.ivBid).toBeCloseTo(0.42);
    expect(out?.ivTrade).toBeCloseTo(0.44);
    expect(out?.delta).toBeCloseTo(0.1);
  });

  it("rejects a payload from a different session than the row", () => {
    expect(resolveDashboardAnalytics([analytics()], quote(), "2026-09-08")).toBeNull();
  });

  it("rejects everything when the row has no price at all", () => {
    // The reported bug: blank prices must not carry IV.
    const blank = quote({ lastPrice: null, bidPrice: null, askPrice: null } as Partial<MarketQuote>);
    expect(resolveDashboardAnalytics([analytics()], blank, S)).toBeNull();
  });

  it("rejects a payload the engine itself marked unavailable", () => {
    expect(resolveDashboardAnalytics([analytics({ isAvailable: false })], quote(), S)).toBeNull();
  });

  it("rejects a payload with no underlying provenance", () => {
    expect(resolveDashboardAnalytics([analytics({ inputProvenance: {} })], quote(), S)).toBeNull();
  });

  it("rejects when the underlying was priced in another session", () => {
    const a = analytics({ inputProvenance: {
      underlying: { sessionDate: "2026-09-04" }, book: { sessionDate: S }, trade: { sessionDate: S },
    } });
    expect(resolveDashboardAnalytics([a], quote(), S)).toBeNull();
  });

  it("drops one IV whose price has moved since it was computed, keeping the others", () => {
    // BID moved 1120 -> 1125; IV_BID no longer describes it, IV_ASK/IV_TRADE still do.
    const out = resolveDashboardAnalytics([analytics()], quote({ bidPrice: 1125 }), S);
    expect(out?.ivBid).toBeNull();
    expect(out?.ivAsk).toBeCloseTo(0.45);
    expect(out?.ivTrade).toBeCloseTo(0.44);
  });

  it("voids ivMid when either side is gone", () => {
    const out = resolveDashboardAnalytics([analytics()], quote({ bidPrice: 1125 }), S);
    expect(out?.ivMid).toBeNull();
  });

  it("voids ivMid on a crossed book", () => {
    const a = analytics({ modelInputs: {
      underlying_price: 25000, market_bid: 1140, market_ask: 1120, market_last: 1130 } });
    const out = resolveDashboardAnalytics([a], quote({ bidPrice: 1140, askPrice: 1120 }), S);
    expect(out?.ivMid).toBeNull();
  });

  it("voids the Greeks when the volatility they were struck from is gone", () => {
    // greeksVolatilitySource is IV_TRADE; move the trade price and the Greeks lose meaning.
    const out = resolveDashboardAnalytics([analytics()], quote({ lastPrice: 1135 }), S);
    expect(out?.ivTrade).toBeNull();
    for (const g of ["delta", "gamma", "theta", "vega", "rho"]) expect(out?.[g]).toBeNull();
  });

  it("does not attach IV_TRADE to a newer confirmed match revision", () => {
    const a = analytics({
      modelInputs: {
        underlying_price: 25000,
        market_bid: 1120,
        market_ask: 1140,
        market_last: 1130,
        market_last_revision: 7,
      },
    });
    const out = resolveDashboardAnalytics([a], quote({ tradeRevision: 8 }), S);
    expect(out?.ivBid).toBeCloseTo(0.42);
    expect(out?.ivAsk).toBeCloseTo(0.45);
    expect(out?.ivTrade).toBeNull();
    expect(out?.delta).toBeNull();
  });

  it("accepts IV_TRADE calculated for the current confirmed match revision", () => {
    const a = analytics({
      modelInputs: {
        underlying_price: 25000,
        market_bid: 1120,
        market_ask: 1140,
        market_last: 1130,
        market_last_revision: 8,
      },
    });
    expect(resolveDashboardAnalytics([a], quote({ tradeRevision: 8 }), S)?.ivTrade)
      .toBeCloseTo(0.44);
  });

  it("keeps the Greeks when a different IV moved than the one they used", () => {
    const out = resolveDashboardAnalytics([analytics()], quote({ bidPrice: 1125 }), S);
    expect(out?.delta).toBeCloseTo(0.1);
  });

  it("rejects when the underlying quote disagrees with the priced spot", () => {
    const und = { marketSessionDate: S, lastPrice: 25100 } as MarketQuote;
    expect(resolveDashboardAnalytics([analytics()], quote(), S, und)).toBeNull();
  });

  it("prefers the most recently calculated of several candidates", () => {
    const older = analytics({ ivTrade: 0.40, calculatedAt: `${S}T09:30:00+07:00` });
    const newer = analytics({ ivTrade: 0.44, calculatedAt: `${S}T14:45:00+07:00` });
    expect(resolveDashboardAnalytics([older, newer], quote(), S)?.ivTrade).toBeCloseTo(0.44);
  });

  it("ignores null and undefined candidates rather than throwing", () => {
    expect(resolveDashboardAnalytics([null, undefined, analytics()], quote(), S)?.ivTrade)
      .toBeCloseTo(0.44);
    expect(resolveDashboardAnalytics([null, undefined], quote(), S)).toBeNull();
  });
});

describe("normalizeAnalytics", () => {
  it("accepts either snake_case or camelCase from the wire", () => {
    const out = normalizeAnalytics({
      iv_bid: 0.42, iv_trade: 0.44, session_date: S, is_available: true,
      model_inputs: { days_to_expiry: 203 }, greeks: { delta: 0.1, theoretical_price: 150.27 },
    });
    expect(out.ivBid).toBeCloseTo(0.42);
    expect(out.sessionDate).toBe(S);
    expect(out.isAvailable).toBe(true);
    expect(out.delta).toBeCloseTo(0.1);
    expect(out.theoreticalPrice).toBeCloseTo(150.27);
    expect(out.dte).toBe(203);
  });

  it("preserves a deliberate null instead of falling through to a stale alias", () => {
    // An engine that says "IV_BID is null" is making a statement, not leaving a gap.
    expect(normalizeAnalytics({ ivBid: null, iv_bid: 0.42 }).ivBid).toBeNull();
  });
});
