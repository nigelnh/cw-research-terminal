import { describe, it, expect } from "vitest";
import { createProviders } from "../data/providers/provider_factory";
import { MockMarketDataProvider } from "../data/mock/mock_market_data_provider";
import { BackendMarketDataProvider } from "../data/backend/backend_market_data_provider";

describe("CW Research Platform - ProviderFactory Composition", () => {
  it("creates mock providers when mode is 'mock'", () => {
    const mockSuite = createProviders("mock");
    expect(mockSuite.marketData).toBeInstanceOf(MockMarketDataProvider);
  });

  it("creates live backend providers when mode is 'live'", () => {
    const liveSuite = createProviders("live");
    expect(liveSuite.marketData).toBeInstanceOf(BackendMarketDataProvider);
  });

  it("defaults to mock providers when no mode is explicitly passed and default env is mock", () => {
    const defaultSuite = createProviders();
    expect(defaultSuite.marketData).toBeInstanceOf(MockMarketDataProvider);
  });
});
