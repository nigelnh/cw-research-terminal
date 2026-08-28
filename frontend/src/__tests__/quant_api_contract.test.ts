import { describe, it, expect, beforeEach } from "vitest";
import { BackendWebSocketClient } from "../data/backend/backend_websocket_client";
import { BackendQuantProvider } from "../data/backend/backend_quant_provider";
import { normalizeTransportIVToDecimal, normalizeTransportPriceToRawVnd } from "../data/backend/mappers/map_snapshot";

/**
 * The frontend owns NO financial math. These tests verify that it CONSUMES the
 * Python backend's quant contract with the correct units and scaling - the real
 * risk once the reimplemented "golden" tests are gone.
 *
 * Backend wire contract (see backend/app/quant/quant_schemas.py + market_schemas.py):
 *   analytics_patch.analytics.iv_bid / iv_trade / iv_ask   -> decimal (0.32 == 32%)
 *   analytics_patch.analytics.greeks.delta                 -> per warrant, dimensionless
 *   analytics_patch.analytics.greeks.gamma                 -> 1/VND
 *   analytics_patch.analytics.greeks.theta                 -> VND per calendar day
 *   analytics_patch.analytics.greeks.vega / rho            -> VND per +0.01 move
 *   analytics_patch.analytics.greeks.theoretical_price     -> raw VND per warrant
 *   analytics_patch.analytics.historical_volatility        -> decimal
 *   analytics_patch.analytics.moneyness                    -> S / K ratio
 *   -> all of the above pass through UNSCALED (no x1000, no /100).
 *
 *   snapshot/patch price fields (Traded, Bid1_Prc, ...)    -> thousand-VND transport (x1000 on ingest)
 *   snapshot/patch Vol1 / Vol2 / Vol3                      -> percent transport (/100 on ingest)
 */
describe("Quant API contract - frontend consumes backend units correctly", () => {
  let client: BackendWebSocketClient;

  beforeEach(() => {
    client = new BackendWebSocketClient("ws://localhost:8501/ws/market");
    // analytics_patch only updates an EXISTING warrant - seed one via a snapshot first.
    client.handleIncomingMessage({
      type: "snapshot",
      symbol: "CHPG2541",
      row: { Symbol: "CHPG2541", Traded: 1.35, Strike_Prc: 28.0, Ratio: 3.5704, Under_Symbol: "HPG", _ts_source: 1000 },
    });
  });

  it("passes analytics_patch Greeks through with NO scaling (raw VND / dimensionless)", () => {
    client.handleIncomingMessage({
      type: "analytics_patch",
      symbol: "CHPG2541",
      analytics: {
        symbol: "CHPG2541",
        moneyness: 1.0714,
        historical_volatility: 0.2264,
        greeks: {
          theoretical_price: 648.26,   // raw VND per warrant
          delta: 0.28835,              // per warrant
          gamma: 0.00006996,           // 1/VND
          theta: -3.93,                // VND / calendar day
          vega: 21.15,                 // VND / +1 vol point
          rho: 13.67,                  // VND / +1 rate point
        },
      },
    });

    const cw = client.getCoveredWarrant("CHPG2541")!;
    expect(cw.theoreticalPrice).toBe(648.26);       // NOT 648260 (would be x1000)
    expect(cw.delta).toBe(0.28835);
    expect(cw.gamma).toBe(0.00006996);
    expect(cw.theta).toBe(-3.93);                    // NOT -3930
    expect(cw.vega).toBe(21.15);                     // NOT 2115 and NOT 0.2115
    expect(cw.rho).toBe(13.67);
    expect(cw.moneynessRatio).toBe(1.0714);
    expect(cw.historicalVolatility).toBe(0.2264);    // stays decimal, NOT 22.64
  });

  it("keeps analytics_patch IVs as decimals (NOT re-divided by 100)", () => {
    client.handleIncomingMessage({
      type: "analytics_patch",
      symbol: "CHPG2541",
      analytics: {
        symbol: "CHPG2541",
        greeks: {},
        iv_bid: 0.312,
        iv_trade: 0.318,
        iv_ask: 0.325,
      },
    });

    const cw = client.getCoveredWarrant("CHPG2541")!;
    expect(cw.ivBid).toBe(0.312);
    expect(cw.ivTrade).toBe(0.318);
    expect(cw.ivAsk).toBe(0.325);
  });

  it("DOES apply x1000 to snapshot/patch price fields (different transport, same message stream)", () => {
    client.handleIncomingMessage({
      type: "patch",
      symbol: "CHPG2541",
      patch: { Symbol: "CHPG2541", Traded: 1.38, Bid1_Prc: 1.35, Ask1_Prc: 1.41, _ts_source: 2000 },
    });
    const cw = client.getCoveredWarrant("CHPG2541")!;
    expect(cw.quote.lastPrice).toBe(1380);          // thousand-VND transport -> raw VND
    expect(cw.quote.bidPrice).toBe(1350);
    expect(cw.quote.askPrice).toBe(1410);
  });

  it("DOES apply /100 to snapshot/patch Vol1/2/3 IV fields (percent transport)", () => {
    client.handleIncomingMessage({
      type: "patch",
      symbol: "CHPG2541",
      patch: { Symbol: "CHPG2541", Vol1: 32.5, Vol2: 31.8, Vol3: 31.2, _ts_source: 3000 },
    });
    const cw = client.getCoveredWarrant("CHPG2541")!;
    expect(cw.ivAsk).toBe(0.325);
    expect(cw.ivTrade).toBe(0.318);
    expect(cw.ivBid).toBe(0.312);
  });

  it("analytics_patch is ignored for an unknown symbol (no fabricated warrant)", () => {
    client.handleIncomingMessage({
      type: "analytics_patch",
      symbol: "CNOTSEEN9",
      analytics: { symbol: "CNOTSEEN9", greeks: { delta: 0.5 } },
    });
    expect(client.getCoveredWarrant("CNOTSEEN9")).toBeUndefined();
  });

  it("non-numeric Greek values do not overwrite existing values", () => {
    client.handleIncomingMessage({
      type: "analytics_patch",
      symbol: "CHPG2541",
      analytics: { symbol: "CHPG2541", greeks: { delta: 0.30, vega: 20.0 } },
    });
    client.handleIncomingMessage({
      type: "analytics_patch",
      symbol: "CHPG2541",
      analytics: { symbol: "CHPG2541", greeks: { delta: null, vega: "n/a" } },
    });
    const cw = client.getCoveredWarrant("CHPG2541")!;
    expect(cw.delta).toBe(0.30);
    expect(cw.vega).toBe(20.0);
  });
});

describe("Quant API contract - transport normalizers", () => {
  it("percent IV -> decimal; negative sentinels -> null", () => {
    expect(normalizeTransportIVToDecimal(32.5)).toBe(0.325);
    expect(normalizeTransportIVToDecimal(0)).toBe(0);
    expect(normalizeTransportIVToDecimal(-1)).toBeNull();
    expect(normalizeTransportIVToDecimal(-2)).toBeNull();
    expect(normalizeTransportIVToDecimal(null)).toBeNull();
  });

  it("thousand-VND -> raw VND is an exact x1000 (protocol, not magnitude heuristic)", () => {
    expect(normalizeTransportPriceToRawVnd(29.5)).toBe(29500);
    expect(normalizeTransportPriceToRawVnd(1.35)).toBe(1350);
    expect(normalizeTransportPriceToRawVnd(0.88)).toBe(880);
    expect(normalizeTransportPriceToRawVnd(null)).toBeNull();
  });
});

describe("Quant API contract - BackendQuantProvider maps /api/quant/calculate response", () => {
  it("maps camelCase pricing fields through, coercing non-numbers to null", async () => {
    const fakeClient: any = {
      calculatePricing: async (_params: any) => ({
        theoreticalPrice: 648.26,
        delta: 0.28835,
        gamma: 0.00006996,
        theta: -3.93,
        vega: 21.15,
        impliedVolatility: 0.2591,
      }),
    };
    const provider = new BackendQuantProvider(fakeClient);
    const res = await provider.calculateGreeks({
      underlyingPrice: 22100,
      strikePrice: 22000,
      timeToMaturity: 0.23886,
      riskFreeRate: 0.05,
      volatility: 0.2591,
      exerciseRatio: 2.0,
    });

    expect(res.theoreticalPrice).toBe(648.26);
    expect(res.delta).toBe(0.28835);
    expect(res.gamma).toBe(0.00006996);
    expect(res.theta).toBe(-3.93);
    expect(res.vega).toBe(21.15);
    expect(res.impliedVolatility).toBe(0.2591);
  });

  it("coerces missing / non-numeric response fields to null (no NaN leakage)", async () => {
    const fakeClient: any = {
      calculatePricing: async () => ({ theoreticalPrice: null, delta: "x", impliedVolatility: undefined }),
    };
    const provider = new BackendQuantProvider(fakeClient);
    const res = await provider.calculateGreeks({} as any);
    expect(res.theoreticalPrice).toBeNull();
    expect(res.delta).toBeNull();
    expect(res.gamma).toBeNull();
    expect(res.impliedVolatility).toBeNull();
  });
});
