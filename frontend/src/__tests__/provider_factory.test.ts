import { describe, it, expect } from "vitest";
import { createProviders } from "../data/providers/provider_factory";
import { BackendMarketDataProvider } from "../data/backend/backend_market_data_provider";
import { BackendInstrumentProvider } from "../data/backend/backend_instrument_provider";
import { BackendHistoricalDataProvider } from "../data/backend/backend_historical_data_provider";
import { BackendQuantProvider } from "../data/backend/backend_quant_provider";

describe("CW Research Platform - ProviderFactory Composition (Live Only)", () => {
  it("1. Creates live backend providers suite unconditionally", () => {
    const suite = createProviders();
    expect(suite.marketData).toBeInstanceOf(BackendMarketDataProvider);
    expect(suite.instruments).toBeInstanceOf(BackendInstrumentProvider);
    expect(suite.historicalData).toBeInstanceOf(BackendHistoricalDataProvider);
    expect(suite.quant).toBeInstanceOf(BackendQuantProvider);
  });

  it("2. Explicit 'live' mode creates live backend providers", () => {
    const liveSuite = createProviders("live");
    expect(liveSuite.marketData).toBeInstanceOf(BackendMarketDataProvider);
    expect(liveSuite.instruments).toBeInstanceOf(BackendInstrumentProvider);
  });

  it("3. Does not fallback to mock providers when unknown or legacy mode is passed", () => {
    const suite = createProviders("mock");
    expect(suite.marketData).toBeInstanceOf(BackendMarketDataProvider);
    expect(suite.instruments).toBeInstanceOf(BackendInstrumentProvider);
  });
});
