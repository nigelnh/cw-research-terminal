import type { MarketQuote } from "./market_quote";

/**
 * Canonical Covered Warrant Specification & State Model
 */
export interface CoveredWarrant {
  symbol: string;
  issuer: string | null;

  // Underlying Relationship
  underlyingSymbol: string;
  underlyingPrice: number | null;

  // Contract Terms
  strikePrice: number;
  exerciseRatio: number; // e.g. 2.0 (for 2:1 ratio)

  // Lifespan & Schedule
  issueDate?: string | null;
  lastTradingDate: string | null;
  maturityDate: string;

  // Real-time Market Quote
  quote: MarketQuote;

  // Real-time Implied Volatility (From cw_gui Vol1 / Vol2 / Vol3)
  ivAsk: number | null;
  ivTrade: number | null;
  ivBid: number | null;

  // Real-time Quantitative Greeks & Valuation
  theoreticalPrice?: number | null;
  modelPriceAtIvMid?: number | null;
  theoreticalVolatility?: number | null;
  theoreticalVolatilitySource?: string | null;
  delta?: number | null;
  gamma?: number | null;
  theta?: number | null;
  vega?: number | null;
  rho?: number | null;
  moneynessRatio?: number | null;
  historicalVolatility?: number | null;

  // Supply / Listing info
  listedVolume?: number | null;
  outstandingVolume?: number | null;
}

export interface CoveredWarrantSnapshot extends CoveredWarrant {
  daysToMaturity: number | null;
  timeToMaturity: number | null;
  moneyness: number | null; // (S - K) / K or S / K
  spread: number | null;    // Ask - Bid
  spreadPercent: number | null; // (Ask - Bid) / Bid
}
