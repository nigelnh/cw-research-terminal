import type { WarrantGreeks, HistoricalVolatilityPoint, BetaPoint } from "@/domain/models";
import type { DateRange } from "./historical_data_provider";

export interface PricingParams {
  underlyingPrice: number;
  strikePrice: number;
  timeToMaturity: number;
  riskFreeRate: number;
  volatility: number;
  exerciseRatio: number;
  marketPrice?: number;
}

export interface PricingResult extends WarrantGreeks {
  impliedVolatility?: number | null;
}

export interface QuantProvider {
  calculateGreeks(params: PricingParams): Promise<PricingResult>;
  getHistoricalVolatility(symbol: string, range?: DateRange): Promise<HistoricalVolatilityPoint[]>;
  getBeta(symbol: string, range?: DateRange): Promise<BetaPoint[]>;
}
