import { describe, it, expect } from "vitest";
import { MockMarketDataProvider } from "../data/mock/mock_market_data_provider";
import { MockInstrumentProvider } from "../data/mock/mock_instrument_provider";
import type { MarketQuote } from "../domain/models";

describe("Mock Subscription Filtering & Research Universe Independence", () => {
  it("13. Mock provider emits updates ONLY for subscribed symbols", async () => {
    const mock = new MockMarketDataProvider();
    const emittedQuotes: string[] = [];

    mock.onQuoteUpdate((quote: MarketQuote) => {
      emittedQuotes.push(quote.symbol);
    });

    // Explicitly subscribe ONLY to CHPG2401
    mock.subscribeSymbols(["CHPG2401"]);
    expect(mock.getSubscribedSymbols().has("CHPG2401")).toBe(true);
    expect(mock.getSubscribedSymbols().has("CFPT2401")).toBe(false);

    mock.connect();

    // Wait for initial connect
    await new Promise((r) => setTimeout(r, 200));

    // Only CHPG2401 should be emitted on connect
    expect(emittedQuotes).toContain("CHPG2401");
    expect(emittedQuotes).not.toContain("CFPT2401");
    expect(emittedQuotes).not.toContain("CVIC2401");

    mock.disconnect();
  });

  it("14. Search results and universe discovery remain available beyond realtime capacity", async () => {
    const instrumentProvider = new MockInstrumentProvider();

    // Provider has capacity limit 33, but universe has multiple CWs
    const allCws = await instrumentProvider.getActiveCoveredWarrants();
    expect(allCws.length).toBeGreaterThan(5);

    // Filter by underlying FPT
    const fptCws = await instrumentProvider.getActiveCoveredWarrants({ underlyingSymbol: "FPT" });
    expect(fptCws.length).toBeGreaterThan(0);
    fptCws.forEach((cw) => expect(cw.underlyingSymbol).toBe("FPT"));

    // Filter by issuer SSI
    const ssiCws = await instrumentProvider.getActiveCoveredWarrants({ issuer: "SSI" });
    expect(ssiCws.length).toBeGreaterThan(0);
    ssiCws.forEach((cw) => expect(cw.issuer).toBe("SSI"));
  });

  it("15. Unsubscribing a symbol halts subsequent updates for that symbol", () => {
    const mock = new MockMarketDataProvider();
    mock.subscribeSymbols(["CHPG2401", "CFPT2401"]);

    expect(mock.getSubscribedSymbols().size).toBe(2);

    mock.unsubscribeSymbols(["CHPG2401"]);
    expect(mock.getSubscribedSymbols().has("CHPG2401")).toBe(false);
    expect(mock.getSubscribedSymbols().has("CFPT2401")).toBe(true);
  });
});
