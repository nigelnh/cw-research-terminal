import type {
  MarketDataProvider,
  InstrumentProvider,
  HistoricalDataProvider,
  QuantProvider,
} from "./index";

import {
  backendMarketDataProvider,
  backendInstrumentProvider,
  backendHistoricalDataProvider,
  backendQuantProvider,
} from "../backend";

export interface ResearchProviders {
  marketData: MarketDataProvider;
  instruments: InstrumentProvider;
  historicalData: HistoricalDataProvider;
  quant: QuantProvider;
}

/**
 * Creates the provider suite connected to the FastAPI market-data gateway.
 * Strictly operates against real market data with zero mock fallback.
 */
export function createProviders(_mode?: string): ResearchProviders {
  return {
    marketData: backendMarketDataProvider,
    instruments: backendInstrumentProvider,
    historicalData: backendHistoricalDataProvider,
    quant: backendQuantProvider,
  };
}

// Global singleton instance
export const providers: ResearchProviders = createProviders();
