import type { MarketQuote, RealtimePulseMap } from "./market_quote";

/**
 * Canonical Covered Warrant Specification & State Model
 */
export interface CoveredWarrant {
  symbol: string;
  status?: string | null;
  metadataVerification?: string | null;
  issuer: string | null;

  // Underlying Relationship
  underlyingSymbol: string;
  underlyingPrice: number | null;

  // Contract Terms
  strikePrice: number | null;
  exerciseRatio: number | null; // e.g. 2.0 (for 2:1 ratio)

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
  analyticsCalculatedAt?: string | null;
  modelDte?: number | null;
  modelRiskFreeRate?: number | null;
  greeksVolatilitySource?: string | null;
  quantAvailable?: boolean;
  theoreticalPrice?: number | null;
  modelPriceAtIvMid?: number | null;
  theoreticalVolatility?: number | null;
  theoreticalVolatilitySource?: string | null;
  delta?: number | null;
  gamma?: number | null;
  theta?: number | null;
  vega?: number | null;
  rho?: number | null;
  /** Canonical moneyness S/K from the backend quant engine. Never recomputed on the client. */
  moneynessRatio?: number | null;
  /** Canonical ITM | ATM | OTM label from the backend quant engine (uses its configured ATM band). */
  moneynessCategory?: "ITM" | "ATM" | "OTM" | null;
  historicalVolatility?: number | null;
  /** Backend contract-lifecycle state: ACTIVE | NEAR_EXPIRY | LAST_TRADING_DAY | PENDING_MATURITY | EXPIRED | UNKNOWN. */
  contractState?: string | null;
  /** True only while the warrant can still be traded. When false the greeks/IV above are not "live". */
  isTradable?: boolean | null;
  /** Backend diagnostic when analytics are unavailable (e.g. METADATA_NOT_VERIFIED_CURRENT). */
  quantUnavailableReason?: string | null;

  // Supply / Listing info
  listedVolume?: number | null;
  outstandingVolume?: number | null;

  /** Incremental IV/analytics/underlying-value changes; snapshots have no pulses. */
  realtimePulses?: RealtimePulseMap;
}

export interface CoveredWarrantSnapshot extends CoveredWarrant {
  daysToMaturity: number | null;
  timeToMaturity: number | null;
  moneyness: number | null; // canonical S/K from the backend
  spread: number | null; // ask - bid (see domain/quant_display.ts)
  spreadPercent: number | null; // 100 * (ask - bid) / mid  (see domain/quant_display.ts)
}
