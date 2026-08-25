import { describe, it, expect } from "vitest";
import {
  mapRawSnapshotToCoveredWarrant,
  applyRawPatchToCoveredWarrant,
  mapInstrumentToCoveredWarrant,
  mapRawCWDataToHistoricalBar,
  mapRawComparisonToAdjustedPoint,
  mapRawUnderlyingCloseToPoint,
  mapRawIndexHistoryToBar,
  normalizeTransportPriceToRawVnd,
  normalizeTransportIVToDecimal,
} from "../data/backend/mappers";

describe("CW Research Platform - Normalization Mappers & Unit Conversions", () => {
  it("converts thousand-VND transport prices unconditionally to canonical raw VND without magnitude heuristic", () => {
    // Standard stock and CW quotes in thousand-VND
    expect(normalizeTransportPriceToRawVnd(29.5)).toBe(29500);
    expect(normalizeTransportPriceToRawVnd(28.0)).toBe(28000);
    expect(normalizeTransportPriceToRawVnd(1.35)).toBe(1350);
    expect(normalizeTransportPriceToRawVnd(1.62)).toBe(1620);
    expect(normalizeTransportPriceToRawVnd(0.88)).toBe(880);
    expect(normalizeTransportPriceToRawVnd(0)).toBe(0);
    expect(normalizeTransportPriceToRawVnd(null)).toBeNull();
    expect(normalizeTransportPriceToRawVnd(undefined)).toBeNull();

    // Regression test: Protocol conversion is strictly protocol-defined, not magnitude-heuristics.
    // If transport sends 880 (880 thousand VND), it unconditionally converts to 880,000 VND without arbitrary thresholds.
    expect(normalizeTransportPriceToRawVnd(880)).toBe(880000);
  });

  it("normalizes transport percentage IV (e.g. 32.5) to canonical decimal representation (0.325)", () => {
    expect(normalizeTransportIVToDecimal(32.5)).toBe(0.325);
    expect(normalizeTransportIVToDecimal(31.8)).toBe(0.318);
    expect(normalizeTransportIVToDecimal(31.2)).toBe(0.312);
    expect(normalizeTransportIVToDecimal(0)).toBe(0);

    // Negative sentinels map strictly to null
    expect(normalizeTransportIVToDecimal(-1.0)).toBeNull();
    expect(normalizeTransportIVToDecimal(-2.0)).toBeNull();
    expect(normalizeTransportIVToDecimal(null)).toBeNull();
    expect(normalizeTransportIVToDecimal(undefined)).toBeNull();
  });

  it("normalizes a full thousand-VND cw_gui transport snapshot into canonical raw VND domain model with decimal IV", () => {
    const rawTransport = {
      Symbol: "CHPG2401",
      Issuer: "SSI",
      Under_Symbol: "HPG",
      Under_Prc: 29.5,   // Thousand VND -> 29,500 VND
      Strike_Prc: 28.0,  // Thousand VND -> 28,000 VND
      Ratio: 2.0,        // Dimensionless -> 2.0 (DO NOT MULTIPLY)
      LastTradingDate: "2024-11-18",
      MaturityDate: "2024-11-20",
      Traded: 1.35,      // Thousand VND -> 1,350 VND
      Ref: 1.25,         // Thousand VND -> 1,250 VND
      Ceil: 1.62,        // Thousand VND -> 1,620 VND
      Floor: 0.88,       // Thousand VND -> 880 VND
      Bid1_Prc: 1.34,    // Thousand VND -> 1,340 VND
      Bid1_Qty: 25000,   // Share count -> 25,000 (DO NOT MULTIPLY)
      Ask1_Prc: 1.36,    // Thousand VND -> 1,360 VND
      Ask1_Qty: 30000,   // Share count -> 30,000 (DO NOT MULTIPLY)
      Vol1: 32.5,        // Percentage IV -> 0.325 (canonical decimal)
      Vol2: 31.8,        // Percentage IV -> 0.318 (canonical decimal)
      Vol3: 31.2,        // Percentage IV -> 0.312 (canonical decimal)
      Total_Vol: 500000, // Volume count -> 500,000 (DO NOT MULTIPLY)
      Trading_Val: 675000000,
    };

    const cw = mapRawSnapshotToCoveredWarrant(rawTransport);
    expect(cw.symbol).toBe("CHPG2401");
    expect(cw.issuer).toBe("SSI");
    expect(cw.underlyingSymbol).toBe("HPG");
    expect(cw.underlyingPrice).toBe(29500);
    expect(cw.strikePrice).toBe(28000);
    expect(cw.exerciseRatio).toBe(2.0);
    expect(cw.quote.lastPrice).toBe(1350);
    expect(cw.quote.referencePrice).toBe(1250);
    expect(cw.quote.ceilingPrice).toBe(1620);
    expect(cw.quote.floorPrice).toBe(880);
    expect(cw.quote.bidPrice).toBe(1340);
    expect(cw.quote.bidQuantity).toBe(25000);
    expect(cw.quote.askPrice).toBe(1360);
    expect(cw.quote.askQuantity).toBe(30000);
    expect(cw.quote.totalVolume).toBe(500000);
    expect(cw.ivAsk).toBe(0.325);
    expect(cw.ivTrade).toBe(0.318);
    expect(cw.ivBid).toBe(0.312);
  });

  it("merges partial live patch without destroying unaffected fields and converts IV to decimal", () => {
    const base = mapRawSnapshotToCoveredWarrant({
      Symbol: "CHPG2401",
      Issuer: "SSI",
      Under_Symbol: "HPG",
      Under_Prc: 29.5,
      Strike_Prc: 28.0,
      Ratio: 2.0,
      MaturityDate: "2024-11-20",
      LastTradingDate: "2024-11-18",
      Traded: 1.35,
      Ref: 1.25,
      Bid1_Prc: 1.34,
      Bid1_Qty: 25000,
      Ask1_Prc: 1.36,
      Ask1_Qty: 30000,
      Vol1: 32.5,
      Vol2: 31.8,
      Vol3: 31.2,
    });

    // Partial patch with only Traded and Vol2 in thousand-VND / percentage transport
    const partialPatch = {
      Symbol: "CHPG2401",
      Traded: 1.38, // 1.38 -> 1380
      Vol2: 33.1,   // 33.1 -> 0.331
    };

    const updated = applyRawPatchToCoveredWarrant(base, partialPatch);

    // Updated fields
    expect(updated.quote.lastPrice).toBe(1380);
    expect(updated.ivTrade).toBe(0.331);

    // Unaffected fields MUST remain perfectly preserved
    expect(updated.symbol).toBe("CHPG2401");
    expect(updated.issuer).toBe("SSI");
    expect(updated.underlyingSymbol).toBe("HPG");
    expect(updated.underlyingPrice).toBe(29500);
    expect(updated.strikePrice).toBe(28000);
    expect(updated.exerciseRatio).toBe(2.0);
    expect(updated.lastTradingDate).toBe("2024-11-18");
    expect(updated.maturityDate).toBe("2024-11-20");
    expect(updated.quote.referencePrice).toBe(1250);
    expect(updated.quote.bidPrice).toBe(1340);
    expect(updated.quote.bidQuantity).toBe(25000);
    expect(updated.quote.askPrice).toBe(1360);
    expect(updated.quote.askQuantity).toBe(30000);
    expect(updated.ivAsk).toBe(0.325);
    expect(updated.ivBid).toBe(0.312);
  });

  it("maps instrument specifications from active metadata endpoints", () => {
    const rawInstrument = {
      symbol: "CHPG2401",
      issuer_name: "SSI",
      underlying_symbol: "HPG",
      exercise_price: 28000,
      exercise_ratio: 2.0,
      last_trading_date: "2024-11-18",
      maturity_date: "2024-11-20",
    };

    const cw = mapInstrumentToCoveredWarrant(rawInstrument);
    expect(cw.symbol).toBe("CHPG2401");
    expect(cw.issuer).toBe("SSI");
    expect(cw.underlyingSymbol).toBe("HPG");
    expect(cw.strikePrice).toBe(28000);
    expect(cw.exerciseRatio).toBe(2.0);
  });

  it("maps historical CW data and close-only stock data honestly without fake OHLC", () => {
    const rawBar = {
      symbol: "CHPG2401",
      trading_date: "2024-05-20",
      open: 1.25,
      high: 1.40,
      low: 1.20,
      close: 1.35,
      volume: 250000,
      total_match_val: 337500000,
    };
    const bar = mapRawCWDataToHistoricalBar(rawBar);
    expect(bar.symbol).toBe("CHPG2401");
    expect(bar.close).toBe(1.35);
    expect(bar.open).toBe(1.25);
    expect(bar.value).toBe(337500000);

    const rawComparison = {
      stockcode: "HPG",
      tradingdate: "2024-05-20",
      closeprice: 29.5,
      basicprice: 29.0,
      adjustedrate: 1.0,
      totaladjustedrate: 1.0,
      adjustedcloseprice: 29.5,
    };
    const compPoint = mapRawComparisonToAdjustedPoint(rawComparison);
    expect(compPoint.symbol).toBe("HPG");
    expect(compPoint.adjustedClosePrice).toBe(29.5);

    const rawStock = {
      symbol: "HPG",
      trading_date: "2024-05-20",
      close: 29500,
      closeraw: 29800,
    };
    const stockPoint = mapRawUnderlyingCloseToPoint(rawStock);
    expect(stockPoint.symbol).toBe("HPG");
    expect(stockPoint.close).toBe(29500);
    expect(stockPoint.rawClose).toBe(29800);

    const rawIndex = {
      name: "VNINDEX",
      trading_date: "2024-05-20",
      open: 1275.2,
      high: 1282.5,
      low: 1270.1,
      close: 1280.0,
    };
    const indexBar = mapRawIndexHistoryToBar(rawIndex);
    expect(indexBar.name).toBe("VNINDEX");
    expect(indexBar.close).toBe(1280.0);
  });
});
