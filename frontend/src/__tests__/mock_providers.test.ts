import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import {
  MockMarketDataProvider,
  MockInstrumentProvider,
  MockHistoricalDataProvider,
} from "./test_fixtures";

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

  // NOTE: there is no "mock_quant_provider" suite. Quant math (Black-Scholes, Greeks,
  // IV, HV) lives only in the Python backend (app.quant.*) and is verified against
  // independent numerical references in backend/tests/test_quant_*.py. The frontend's
  // job is to consume the backend's quant contract correctly - see quant_api_contract.test.ts.
});
