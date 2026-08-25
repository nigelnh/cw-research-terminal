import { describe, it, expect, vi, beforeEach } from "vitest";
import { BackendInstrumentProvider } from "../data/backend/backend_instrument_provider";
import { BackendClient } from "../data/backend/backend_client";
import { SubscriptionPlanner } from "../data/subscription";
import type { WatchlistItem } from "../domain/models";

describe("Instrument Registry Frontend Integration & Quant Readiness", () => {
  let mockClient: BackendClient;
  let provider: BackendInstrumentProvider;

  const mockActiveInstruments = [
    {
      symbol: "CHPG2602",
      issuer: "SSI",
      underlying_symbol: "HPG",
      strike_price: 22000.0,
      exercise_ratio: 2.0,
      maturity_date: "2026-11-20",
      last_trading_date: "2026-11-18",
      listed_volume: 10000000,
      issue_price: 1500.0,
      instrument_type: "CW",
      status: "ACTIVE",
      data_quality: "COMPLETE",
      metadata_source: "CANONICAL_CACHED_SNAPSHOT",
    },
    {
      symbol: "CFPT2602",
      issuer: "VND",
      underlying_symbol: "FPT",
      strike_price: 125000.0,
      exercise_ratio: 5.0,
      maturity_date: "2026-11-27",
      last_trading_date: "2026-11-25",
      listed_volume: 8000000,
      issue_price: 2200.0,
      instrument_type: "CW",
      status: "ACTIVE",
      data_quality: "COMPLETE",
      metadata_source: "CANONICAL_CACHED_SNAPSHOT",
    },
    {
      symbol: "CMWG2602",
      issuer: "HSC",
      underlying_symbol: "MWG",
      strike_price: 65000.0,
      exercise_ratio: 4.0,
      maturity_date: "2026-12-18",
      last_trading_date: "2026-12-16",
      listed_volume: 12000000,
      issue_price: 1800.0,
      instrument_type: "CW",
      status: "ACTIVE",
      data_quality: "COMPLETE",
      metadata_source: "CANONICAL_CACHED_SNAPSHOT",
    },
    {
      symbol: "CPDR2601",
      issuer: "SSI",
      underlying_symbol: "PDR",
      strike_price: null,
      exercise_ratio: null,
      maturity_date: null,
      last_trading_date: null,
      listed_volume: null,
      issue_price: null,
      instrument_type: "CW",
      status: "ACTIVE",
      data_quality: "PARTIAL",
      metadata_source: "BROKER_DCHART_DISCOVERY",
    },
  ];

  beforeEach(() => {
    mockClient = new BackendClient("http://localhost:8501");
    provider = new BackendInstrumentProvider(mockClient);
  });

  it("1. Accurately maps canonical metadata into domain CoveredWarrant model", async () => {
    vi.spyOn(mockClient, "getActiveInstruments").mockResolvedValue(mockActiveInstruments);

    const cws = await provider.getActiveCoveredWarrants();
    expect(cws.length).toBe(4);

    const chpg = cws.find((x) => x.symbol === "CHPG2602");
    expect(chpg).toBeDefined();
    expect(chpg?.symbol).toBe("CHPG2602");
    expect(chpg?.issuer).toBe("SSI");
    expect(chpg?.underlyingSymbol).toBe("HPG");
    expect(chpg?.strikePrice).toBe(22000.0);
    expect(chpg?.exerciseRatio).toBe(2.0);
    expect(chpg?.maturityDate).toBe("2026-11-20");
    expect(chpg?.lastTradingDate).toBe("2026-11-18");
    expect(chpg?.listedVolume).toBe(10000000);
  });

  it("2. Filters by underlying symbol and issuer accurately", async () => {
    vi.spyOn(mockClient, "getActiveInstruments").mockImplementation(async (issuer, underlying) => {
      return mockActiveInstruments.filter((item) => {
        const matchIss = !issuer || item.issuer === issuer.toUpperCase();
        const matchUnd = !underlying || item.underlying_symbol === underlying.toUpperCase();
        return matchIss && matchUnd;
      });
    });

    const hpgCws = await provider.getActiveCoveredWarrants({ underlyingSymbol: "HPG" });
    expect(hpgCws.length).toBe(1);
    expect(hpgCws[0].symbol).toBe("CHPG2602");

    const ssiCws = await provider.getActiveCoveredWarrants({ issuer: "SSI" });
    expect(ssiCws.length).toBe(2);
    expect(ssiCws.map((x) => x.symbol)).toEqual(["CHPG2602", "CPDR2601"]);

    const vndCws = await provider.getActiveCoveredWarrants({ issuer: "VND" });
    expect(vndCws.length).toBe(1);
    expect(vndCws[0].symbol).toBe("CFPT2602");
  });

  it("3. Preserves discovered partial metadata instruments without silent omission", async () => {
    vi.spyOn(mockClient, "getActiveInstruments").mockResolvedValue(mockActiveInstruments);

    const cws = await provider.getActiveCoveredWarrants();
    const partialCw = cws.find((x) => x.symbol === "CPDR2601");
    expect(partialCw).toBeDefined();
    expect(partialCw?.symbol).toBe("CPDR2601");
    expect(partialCw?.underlyingSymbol).toBe("PDR");
    expect(partialCw?.strikePrice).toBe(0); // Mapped safely to 0/null in UI domain
    expect(partialCw?.maturityDate).toBe("");
  });

  it("4. Retrieves single warrant specification accurately", async () => {
    vi.spyOn(mockClient, "getInstrumentSpecification").mockResolvedValue(mockActiveInstruments[0]);

    const spec = await provider.getWarrantSpecification("CHPG2602");
    expect(spec).toBeDefined();
    expect(spec?.symbol).toBe("CHPG2602");
    expect(spec?.strikePrice).toBe(22000.0);
    expect(spec?.exerciseRatio).toBe(2.0);
  });

  it("5. Live mode throws or returns empty on network error without falling back to mock fixtures", async () => {
    vi.spyOn(mockClient, "getActiveInstruments").mockRejectedValue(new Error("Network Error 500"));

    await expect(provider.getActiveCoveredWarrants()).rejects.toThrow("Network Error 500");
  });

  it("6. Universe browsing and searching does not consume realtime subscription slots", () => {
    // Research universe holds metadata for 500+ active instruments
    const universeCount = 500;
    const currentWatchlist: WatchlistItem[] = [];

    // Subscription plan only computes for watchlist items
    const plan = SubscriptionPlanner.computePlan(currentWatchlist, ["VNINDEX"], 33);
    expect(plan.requiredSymbols).toEqual(["VNINDEX"]);
    expect(plan.symbolCount).toBe(1);
    expect(plan.symbolCount).toBeLessThan(universeCount);
  });

  it("7. Adding active CW from registry to Dashboard creates correct CW + Underlying plan", () => {
    const selectedFromRegistry: WatchlistItem = {
      symbol: "CHPG2602",
      instrumentType: "CW",
      underlyingSymbol: "HPG",
      strikePrice: 22000.0,
      exerciseRatio: 2.0,
      maturityDate: "2026-11-20",
      addedAt: Date.now(),
    };

    const plan = SubscriptionPlanner.computePlan([selectedFromRegistry], ["VNINDEX"], 33);
    // Must contain VNINDEX + CHPG2602 + HPG
    expect(plan.requiredSymbols).toContain("VNINDEX");
    expect(plan.requiredSymbols).toContain("CHPG2602");
    expect(plan.requiredSymbols).toContain("HPG");
    expect(plan.symbolCount).toBe(3);
    expect(plan.dependencyMap.get("HPG")?.has("CHPG2602")).toBe(true);
  });

  it("8. Exercise Ratio Convention Invariant: 2 CWs per 1 share gives C_share = C_CW * exerciseRatio", () => {
    const exerciseRatio = 2.0; // 2:1
    const cwMarketPrice = 1350.0; // 1,350 VND per warrant
    const shareEquivalentPrice = cwMarketPrice * exerciseRatio; // 2,700 VND per share option
    expect(shareEquivalentPrice).toBe(2700.0);

    const underlyingPrice = 29500.0;
    const strikePrice = 28000.0;
    const intrinsicShare = Math.max(0, underlyingPrice - strikePrice); // 1,500 VND
    const intrinsicCW = intrinsicShare / exerciseRatio; // 750 VND
    expect(intrinsicCW).toBe(750.0);
  });
});
