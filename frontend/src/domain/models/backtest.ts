import type { StrategyDefinition } from "./strategy";

/**
 * Backtesting & Portfolio Simulation Domain Models
 */

export interface BacktestTrade {
  symbol: string;
  underlyingSymbol: string;
  entryDate: string;
  entryPrice: number;
  exitDate: string;
  exitPrice: number;
  quantity: number;
  grossPnL: number;
  costs: number;
  netPnL: number;
  returnPct: number;
  holdingPeriodDays: number;
  entryReasons: string[];
  exitReasons: string[];
}

export interface EquityCurvePoint {
  date: string;
  portfolioValue: number;
  cash: number;
  investedValue: number;
  drawdownPct: number;
  benchmarkValue?: number;
}

export interface BacktestPerformanceMetrics {
  totalReturnPct: number;
  annualizedReturnPct: number | null;
  maxDrawdownPct: number;
  sharpeRatio: number | null;
  sortinoRatio: number | null;
  winRatePct: number;
  profitFactor: number | null;
  totalTrades: number;
  winningTrades: number;
  losingTrades: number;
  averageWinAmt: number;
  averageLossAmt: number;
  averageHoldingDays: number;
}

export interface BacktestConfig {
  startDate: string;
  endDate: string;
  initialCapital: number;
  transactionCostBps: number; // e.g. 15 bps (0.15%)
  slippageBps: number;        // e.g. 10 bps (0.10%)
  benchmarkSymbol?: string;   // e.g. VNINDEX
}

export interface BacktestResult {
  id: string;
  strategy: StrategyDefinition;
  config: BacktestConfig;
  metrics: BacktestPerformanceMetrics;
  equityCurve: EquityCurvePoint[];
  trades: BacktestTrade[];
  generatedAt: string;
}
