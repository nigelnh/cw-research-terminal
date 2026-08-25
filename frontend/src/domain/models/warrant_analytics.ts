/**
 * Canonical Quantitative Analytics & Greeks Model
 */
export interface WarrantGreeks {
  theoreticalPrice: number | null;
  delta: number | null;
  gamma: number | null;
  theta: number | null;
  vega: number | null;
  rho?: number | null;
}

export interface HistoricalVolatilityPoint {
  symbol: string;
  date: string;
  hv22: number | null;
  hv66: number | null;
  hv132: number | null;
  hv252: number | null;
}

export interface BetaPoint {
  symbol: string;
  date: string;
  beta1m: number | null;
  beta3m: number | null;
  beta12m: number | null;
}

export interface WarrantAnalytics {
  symbol: string;
  greeks: WarrantGreeks;
  historicalVolatility: HistoricalVolatilityPoint | null;
  beta: BetaPoint | null;
  volatilityPremium: {
    ivVsHv22: number | null; // ivTrade - hv22
    ivVsHv66: number | null; // ivTrade - hv66
  };
}
