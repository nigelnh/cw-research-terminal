/**
 * Strategy & Rule Primitives for Covered Warrant Quantitative Research
 */

export interface ResearchRow {
  date: string; // Evaluation Date T

  symbol: string;
  underlyingSymbol: string;
  issuer?: string | null;

  // CW Historical Pricing
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  volume: number | null;

  // Corporate Action Adjusted Underlying Close (T <= date)
  underlyingAdjustedClose: number | null;

  // Terms
  strikePrice: number;
  exerciseRatio: number;
  daysToMaturity: number;
  moneyness: number | null; // (S - K) / K

  // Quantitative Attributes (T <= date)
  hv22: number | null;
  hv66: number | null;
  hv132: number | null;
  hv252: number | null;

  beta1m?: number | null;
  beta3m?: number | null;
  beta12m?: number | null;

  ivTrade?: number | null;
  volatilityPremium?: number | null; // ivTrade - hv22
}

export interface StrategyContext {
  currentDate: string;
  capital: number;
  availableCash: number;
  activePositions: Map<string, SimulatedPosition>;
}

export interface SimulatedPosition {
  symbol: string;
  underlyingSymbol: string;
  quantity: number;
  entryPrice: number;
  entryDate: string;
  strategyId?: string;
}

export interface StrategyRule {
  id: string;
  name: string;
  description?: string;
  evaluate(current: ResearchRow, context: StrategyContext): boolean;
}

export interface StrategyDefinition {
  id: string;
  name: string;
  description: string;
  rules: StrategyRule[];
  holdingPeriodDays?: number;
  takeProfitPct?: number;
  stopLossPct?: number;
  maxAllocationPerWarrantPct?: number;
}
