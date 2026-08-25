import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import {
  MockMarketDataProvider,
  MockInstrumentProvider,
  MockHistoricalDataProvider,
  MockQuantProvider,
} from "../data/mock";

describe("CW Research Platform - Mock Providers Test Suite", () => {
  describe("mock_market_data_provider", () => {
    let provider: MockMarketDataProvider;

    beforeEach(() => {
      vi.useFakeTimers();
      provider = new MockMarketDataProvider();
      provider.subscribeSymbols(["CHPG2401", "CFPT2401", "CMWG2401"]);
    });

    afterEach(() => {
      provider.disconnect();
      vi.useRealTimers();
    });

    it("starts in DISCONNECTED state and initializes fixtures", () => {
      expect(provider.getConnectionState()).toBe("DISCONNECTED");
      const quotes = provider.getAllQuotes();
      expect(quotes.size).toBeGreaterThan(0);
      expect(provider.getLatestCoveredWarrant("CHPG2401")).toBeDefined();
    });

    it("transitions to CONNECTED on connect() and emits initial snapshots", () => {
      const emittedCws: any[] = [];
      const states: string[] = [];

      provider.onConnectionStateChange((s) => states.push(s));
      provider.onCoveredWarrantUpdate((cw) => emittedCws.push(cw));

      provider.connect();
      expect(states).toContain("CONNECTING");

      // Advance timers to trigger connection resolution (150ms)
      vi.advanceTimersByTime(200);

      expect(provider.getConnectionState()).toBe("CONNECTED");
      expect(emittedCws.length).toBeGreaterThan(0);
    });

    it("emits periodic simulated patches on timer ticks", () => {
      const patchUpdates: any[] = [];
      provider.onCoveredWarrantUpdate((cw) => patchUpdates.push(cw));

      provider.connect();
      vi.advanceTimersByTime(200); // Connected

      const initialCount = patchUpdates.length;

      // Advance by 1000ms for simulated patch
      vi.advanceTimersByTime(1000);
      expect(patchUpdates.length).toBeGreaterThan(initialCount);
    });

    it("cleans up timer and sets state to DISCONNECTED on disconnect()", () => {
      provider.connect();
      vi.advanceTimersByTime(200);
      expect(provider.getConnectionState()).toBe("CONNECTED");

      provider.disconnect();
      expect(provider.getConnectionState()).toBe("DISCONNECTED");
    });
  });

  describe("mock_instrument_provider", () => {
    const provider = new MockInstrumentProvider();

    it("retrieves active covered warrants from fixtures", async () => {
      const warrants = await provider.getActiveCoveredWarrants();
      expect(warrants.length).toBeGreaterThan(0);
      expect(warrants.some((w) => w.symbol === "CHPG2401")).toBe(true);
    });

    it("filters active warrants by issuer and underlying symbol", async () => {
      const ssiWarrants = await provider.getActiveCoveredWarrants({ issuer: "SSI" });
      expect(ssiWarrants.every((w) => w.issuer === "SSI")).toBe(true);

      const hpgWarrants = await provider.getActiveCoveredWarrants({ underlyingSymbol: "HPG" });
      expect(hpgWarrants.every((w) => w.underlyingSymbol === "HPG")).toBe(true);
    });

    it("retrieves unique underlying symbols list", async () => {
      const underlyings = await provider.getUnderlyingSymbols();
      expect(underlyings).toContain("HPG");
      expect(underlyings).toContain("FPT");
      expect(underlyings).toContain("MWG");
    });
  });

  describe("mock_historical_data_provider", () => {
    const provider = new MockHistoricalDataProvider();

    it("retrieves historical bars for a covered warrant symbol within date range", async () => {
      const bars = await provider.getHistoricalWarrantBars("CHPG2401", {
        fromDate: "2024-05-15",
        toDate: "2024-05-20",
      });
      expect(bars.length).toBeGreaterThan(0);
      expect(bars[0].symbol).toBe("CHPG2401");
      expect(bars[0].close).toBeDefined();
    });

    it("retrieves close-only underlying history without fake OHLC", async () => {
      const history = await provider.getUnderlyingCloseHistory("HPG", {
        fromDate: "2024-05-15",
        toDate: "2024-05-20",
      });
      expect(history.length).toBeGreaterThan(0);
      expect(history[0].symbol).toBe("HPG");
      expect(history[0].close).toBe(28800);
      expect(history[0].rawClose).toBe(28800);
    });

    it("retrieves index history for VNINDEX", async () => {
      const indexBars = await provider.getIndexHistory("VNINDEX", {
        fromDate: "2024-05-15",
        toDate: "2024-05-20",
      });
      expect(indexBars.length).toBeGreaterThan(0);
      expect(indexBars[0].name).toBe("VNINDEX");
    });
  });

  describe("mock_quant_provider", () => {
    const provider = new MockQuantProvider();

    it("calculates Black-Scholes Greeks analytically for standard parameters", async () => {
      const greeks = await provider.calculateGreeks({
        underlyingPrice: 29500,
        strikePrice: 28000,
        timeToMaturity: 0.42,
        riskFreeRate: 0.065,
        volatility: 0.35,
        exerciseRatio: 2.0,
      });

      expect(greeks.theoreticalPrice).toBeGreaterThan(1800);
      expect(greeks.theoreticalPrice).toBeLessThan(2300);
      expect(greeks.delta).toBeGreaterThan(0.30);
      expect(greeks.delta).toBeLessThan(0.50);
      expect(greeks.gamma).toBeGreaterThan(0);
      expect(greeks.theta).toBeLessThan(0);
      expect(greeks.vega).toBeGreaterThan(0);
    });

    it("rejects invalid financial inputs with null values", async () => {
      const invalidSpot = await provider.calculateGreeks({
        underlyingPrice: -100,
        strikePrice: 28000,
        timeToMaturity: 0.42,
        riskFreeRate: 0.065,
        volatility: 0.35,
        exerciseRatio: 2.0,
      });
      expect(invalidSpot.theoreticalPrice).toBeNull();
      expect(invalidSpot.delta).toBeNull();

      const invalidVol = await provider.calculateGreeks({
        underlyingPrice: 29500,
        strikePrice: 28000,
        timeToMaturity: 0.42,
        riskFreeRate: 0.065,
        volatility: -0.5,
        exerciseRatio: 2.0,
      });
      expect(invalidVol.theoreticalPrice).toBeNull();
    });

    it("handles boundary expiry cases (T=0) properly", async () => {
      const expiredITM = await provider.calculateGreeks({
        underlyingPrice: 32000,
        strikePrice: 30000,
        timeToMaturity: 0,
        riskFreeRate: 0.05,
        volatility: 0.30,
        exerciseRatio: 2.0,
      });
      expect(expiredITM.theoreticalPrice).toBe(1000); // (32000 - 30000) / 2
      expect(expiredITM.delta).toBe(0.5); // 1/k
      expect(expiredITM.gamma).toBe(0);
    });
  });
});
