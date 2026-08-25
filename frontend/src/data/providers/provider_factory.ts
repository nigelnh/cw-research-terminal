import { config } from "@/config";
import type {
  MarketDataProvider,
  InstrumentProvider,
  HistoricalDataProvider,
  QuantProvider,
} from "./index";

import {
  mockMarketDataProvider,
  mockInstrumentProvider,
  mockHistoricalDataProvider,
  mockQuantProvider,
} from "../mock";

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
 * Creates provider suite based on configured VITE_DATA_MODE.
 * Prevents scattering `if (mock)` throughout UI components.
 */
export function createProviders(mode?: string): ResearchProviders {
  const selectedMode = mode || config.dataMode;

  if (selectedMode === "live") {
    return {
      marketData: backendMarketDataProvider,
      instruments: backendInstrumentProvider,
      historicalData: backendHistoricalDataProvider,
      quant: backendQuantProvider,
    };
  }

  // Default: Mock providers (Zero external infrastructure required)
  return {
    marketData: mockMarketDataProvider,
    instruments: mockInstrumentProvider,
    historicalData: mockHistoricalDataProvider,
    quant: mockQuantProvider,
  };
}

// Global singleton instance
export const providers: ResearchProviders = createProviders();
