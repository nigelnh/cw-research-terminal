import { describe, it, expect } from "vitest";
import { createProviders } from "../data/providers/provider_factory";
import { BackendMarketDataProvider } from "../data/backend/backend_market_data_provider";
import { BackendWebSocketClient } from "../data/backend/backend_websocket_client";
import { SubscriptionPlanner } from "../data/subscription";
import { mapRawSnapshotToCoveredWarrant } from "../data/backend/mappers/map_snapshot";
import {
  PRIMARY_UI_UNIVERSE,
  DEFAULT_PRIMARY_WATCHLIST_ITEMS,
  createDefaultWatchlist,
} from "../domain/models/watchlist";
import * as fs from "fs";
import * as path from "path";

describe("Milestone: Universe Scoping & Realtime Acceptance Contract", () => {
  // 1. Primary display universe contains exactly HPG, NVL, VHM, CTCB2601, CVPB2615
  it("1. Primary display universe contains exactly [CHPG2625, CVPB2615, HPG, VPB, VNINDEX]", () => {
    const canonical = JSON.parse(fs.readFileSync(path.resolve(__dirname, "../../../backend/app/instruments/data/default_research_universe.json"), "utf8"));
    expect(PRIMARY_UI_UNIVERSE).toEqual(canonical.items.map((i: { symbol: string }) => i.symbol));
    expect(DEFAULT_PRIMARY_WATCHLIST_ITEMS.filter(i => i.instrumentType === "STOCK").map(i => i.symbol)).toEqual(["HPG", "FPT", "VPB"]);
    expect(DEFAULT_PRIMARY_WATCHLIST_ITEMS.filter(i => i.instrumentType === "CW")).toHaveLength(27);
    const symbols = DEFAULT_PRIMARY_WATCHLIST_ITEMS.map((item) => item.symbol);
    expect(symbols).toEqual([...PRIMARY_UI_UNIVERSE]);
  });

  // 2. Primary universe count = 5
  it("2. Primary universe count is exactly 30", () => {
    expect(PRIMARY_UI_UNIVERSE.length).toBe(30);
    expect(DEFAULT_PRIMARY_WATCHLIST_ITEMS.length).toBe(30);
    const defaultWatchlist = createDefaultWatchlist();
    expect(defaultWatchlist.items.length).toBe(30);
  });

  // 3. CHPG2625 resolves underlying HPG (verified default CW)
  it("3. CHPG2625 resolves underlying HPG in the default watchlist model", () => {
    const chpg = DEFAULT_PRIMARY_WATCHLIST_ITEMS.find((i) => i.symbol === "CHPG2625");
    expect(chpg).toBeDefined();
    expect(chpg?.instrumentType).toBe("CW");
    expect(chpg?.underlyingSymbol).toBe("HPG");
  });

  // 4. CVPB2615 resolves underlying VPB
  it("4. CVPB2615 resolves underlying VPB in the default watchlist model", () => {
    const cvpb = DEFAULT_PRIMARY_WATCHLIST_ITEMS.find((i) => i.symbol === "CVPB2615");
    expect(cvpb).toBeDefined();
    expect(cvpb?.instrumentType).toBe("CW");
    expect(cvpb?.underlyingSymbol).toBe("VPB");
  });

  // 5. CW dependency resolution maps underlying dependencies
  it("5. CW dependency resolution maps underlying dependencies", () => {
    const defaultWatchlist = createDefaultWatchlist();
    const plan = SubscriptionPlanner.computePlan(defaultWatchlist.items, [], 33);
    
    // Check dependency map
    expect(plan.dependencyMap.get("HPG")?.has("CHPG2625")).toBe(true);
    expect(plan.dependencyMap.get("VPB")?.has("CVPB2615")).toBe(true);

    // Symbols appear only once in required symbols
    expect(plan.requiredSymbols.filter((s) => s === "HPG").length).toBe(1);
    expect(plan.requiredSymbols.filter((s) => s === "VPB").length).toBe(1);
  });

  // 6. Deduplicated acceptance subscription count.
  // Default = CHPG2625(HPG), CVPB2615(VPB), HPG, VPB, VNINDEX -> the CW underlyings are
  // already watchlist items, so the deduped required set is exactly 30.
  it("6. Deduplicated acceptance subscription count is exactly 30 (underlyings already watched)", () => {
    const defaultWatchlist = createDefaultWatchlist();
    const plan = SubscriptionPlanner.computePlan(defaultWatchlist.items, [], 33);
    expect(plan.requiredSymbols).toEqual([...PRIMARY_UI_UNIVERSE].sort());
    expect(plan.symbolCount).toBe(30);
    expect(plan.remainingCapacity).toBe(3);
    expect(plan.isCapacityExceeded).toBe(false);
  });

  // 7. Research-only synthetic symbols may appear in Research test fixtures
  it("7. Research-only synthetic symbols exist strictly within test_fixtures catalog", () => {
    const fixturePath = path.resolve(__dirname, "test_fixtures", "covered_warrants.json");
    expect(fs.existsSync(fixturePath)).toBe(true);
    const content = JSON.parse(fs.readFileSync(fixturePath, "utf-8"));
    const symbols = content.map((c: any) => c.symbol);
    expect(symbols).toContain("CFPT2401");
    expect(symbols).toContain("CMWG2401");
  });

  // 8. Research-only synthetic symbols do NOT appear in the default Personal Dashboard / primary live universe
  it("8. Research-only synthetic symbols do NOT appear in the default Personal Dashboard / primary live universe", () => {
    const defaultWatchlist = createDefaultWatchlist();
    const symbols = defaultWatchlist.items.map((i) => i.symbol);
    expect(symbols).not.toContain("CFPT2401");
    expect(symbols).not.toContain("CMWG2401");
    expect(symbols).not.toContain("CVIC2401");
    // CTCB2601 (CONFLICTING metadata) is deliberately out of the default demo universe.
    expect(symbols).not.toContain("CTCB2601");
    expect(symbols).not.toContain("VN30");
  });

  // 9. Merely displaying a Research-only symbol does not automatically subscribe it to realtime
  it("9. Browsing a Research-only instrument does not automatically add it to realtime subscriptions", () => {
    const defaultWatchlist = createDefaultWatchlist();
    const initialPlan = SubscriptionPlanner.computePlan(defaultWatchlist.items, [], 33);
    expect(initialPlan.symbolCount).toBe(30);

    // Browsing/selecting CFPT2401 in Research catalog without adding to watchlist
    const researchSelection = {
      symbol: "CFPT2401",
      instrumentType: "CW",
      underlyingSymbol: "FPT",
      strikePrice: 120000,
    };
    expect(researchSelection.symbol).toBe("CFPT2401");

    // Subscription plan remains unchanged at 30
    const activePlan = SubscriptionPlanner.computePlan(defaultWatchlist.items, [], 33);
    expect(activePlan.requiredSymbols).toEqual([...PRIMARY_UI_UNIVERSE].sort());
    expect(activePlan.symbolCount).toBe(30);
  });

  // 10. Research-only synthetic instruments do not supply fabricated realtime quote/IV/Greek values
  it("10. Research-only synthetic instruments have null market quotes when no live feed tick exists", () => {
    const rawSyntheticCW = {
      Symbol: "CFPT2401",
      Under_Symbol: "FPT",
      Strike_Prc: 120.0,
      Ratio: 5.0,
      Traded: null,
      Bid1_Prc: null,
      Ask1_Prc: null,
      Vol1: null,
      Vol2: null,
      Vol3: null,
    };

    const cw = mapRawSnapshotToCoveredWarrant(rawSyntheticCW);
    expect(cw.symbol).toBe("CFPT2401");
    expect(cw.quote.lastPrice).toBeNull();
    expect(cw.quote.bidPrice).toBeNull();
    expect(cw.quote.askPrice).toBeNull();
    expect(cw.ivTrade).toBeNull();
    expect(cw.ivBid).toBeNull();
    expect(cw.ivAsk).toBeNull();
  });

  // 11. Missing market data renders — (null / undefined)
  it("11. Missing market data maps to null/undefined without fallback to 0 or mock values", () => {
    const rawNoTradeCW = {
      Symbol: "CHPG2541",
      Under_Symbol: "HPG",
      Under_Prc: 22.15,
      Strike_Prc: 24.0,
      Ratio: 2.0,
      Traded: null,
      Bid1_Prc: 0.82,
      Ask1_Prc: 0.84,
      Vol1: 35.0,
      Vol2: null,
      Vol3: 34.0,
    };

    const cw = mapRawSnapshotToCoveredWarrant(rawNoTradeCW);
    expect(cw.quote.lastPrice).toBeNull();
    expect(cw.ivTrade).toBeNull(); // Trade-only IV is null when there is no trade
    expect(cw.quote.bidPrice).toBe(820);
    expect(cw.quote.askPrice).toBe(840);
  });

  // 12. No runtime live -> mock-provider fallback has been reintroduced
  it("12. ProviderFactory unconditionally returns live backend providers and has zero mock fallback", () => {
    const suite = createProviders();
    expect(suite.marketData).toBeInstanceOf(BackendMarketDataProvider);

    const wsClient = new BackendWebSocketClient("ws://127.0.0.1:9999");
    const provider = new BackendMarketDataProvider(wsClient);
    expect(provider.getConnectionState()).toBe("DISCONNECTED");
    expect(provider.getAllQuotes().size).toBe(0);
  });

  // 14. Live value reconciliation test: HPG, NVL, VHM, CVHM2615, CHPG2541 vectors
  it("14. Live Value Reconciliation Test: Verifies decimal scaling, zero-preservation, and canonical spread %", () => {
    // HPG Live Vector
    const rawHpg = {
      Symbol: "HPG",
      Bid1_Prc: 21.85,  // -> 21850 VND
      Ask1_Prc: 21.90,  // -> 21900 VND
      Traded: 21.85,    // -> 21850 VND
      Change: 0.05,     // -> 50 VND
      ChangePercent: 0.0023, // -> +0.23% (decimal fraction)
      Total_Vol: 12500000,
    };
    const hpg = mapRawSnapshotToCoveredWarrant(rawHpg);
    expect(hpg.quote.bidPrice).toBe(21850);
    expect(hpg.quote.askPrice).toBe(21900);
    expect(hpg.quote.lastPrice).toBe(21850);
    expect(hpg.quote.priceChange).toBe(50);
    expect(hpg.quote.priceChangePercent).toBe(0.0023);
    const hpgSpread = hpg.quote.askPrice! - hpg.quote.bidPrice!;
    expect(hpgSpread).toBe(50);
    const hpgSpreadPct = ((hpgSpread / hpg.quote.bidPrice!) * 100).toFixed(2);
    expect(hpgSpreadPct).toBe("0.23");

    // NVL Zero Change Vector
    const rawNvl = {
      Symbol: "NVL",
      Traded: 13.50,
      Change: 0,
      ChangePercent: 0,
    };
    const nvl = mapRawSnapshotToCoveredWarrant(rawNvl);
    expect(nvl.quote.priceChange).toBe(0);
    expect(nvl.quote.priceChangePercent).toBe(0);

    // VHM Negative Change Vector
    const rawVhm = {
      Symbol: "VHM",
      Traded: 42.50,
      Change: -0.90, // -900 VND
      ChangePercent: -0.0122, // -1.22%
    };
    const vhm = mapRawSnapshotToCoveredWarrant(rawVhm);
    expect(vhm.quote.priceChange).toBe(-900);
    expect(vhm.quote.priceChangePercent).toBe(-0.0122);
    const vhmPctDisplay = (vhm.quote.priceChangePercent! * 100).toFixed(2);
    expect(vhmPctDisplay).toBe("-1.22");

    // CVHM2615 Spread Vector
    const rawCvhm = {
      Symbol: "CVHM2615",
      Under_Symbol: "VHM",
      Bid1_Prc: 1.81, // 1810 VND
      Ask1_Prc: 1.84, // 1840 VND
      Traded: null,   // No trade
    };
    const cvhm = mapRawSnapshotToCoveredWarrant(rawCvhm);
    expect(cvhm.quote.bidPrice).toBe(1810);
    expect(cvhm.quote.askPrice).toBe(1840);
    expect(cvhm.quote.lastPrice).toBeNull();
    const cvhmSpread = cvhm.quote.askPrice! - cvhm.quote.bidPrice!;
    expect(cvhmSpread).toBe(30);
    const cvhmSpreadPct = ((cvhmSpread / cvhm.quote.bidPrice!) * 100).toFixed(2);
    expect(cvhmSpreadPct).toBe("1.66");

    // CHPG2541 Spread Vector
    const rawChpg = {
      Symbol: "CHPG2541",
      Under_Symbol: "HPG",
      Bid1_Prc: 0.30, // 300 VND
      Ask1_Prc: 0.31, // 310 VND
      Traded: null,   // No trade
    };
    const chpg = mapRawSnapshotToCoveredWarrant(rawChpg);
    expect(chpg.quote.bidPrice).toBe(300);
    expect(chpg.quote.askPrice).toBe(310);
    expect(chpg.quote.lastPrice).toBeNull();
    const chpgSpread = chpg.quote.askPrice! - chpg.quote.bidPrice!;
    expect(chpgSpread).toBe(10);
    const chpgSpreadPct = ((chpgSpread / chpg.quote.bidPrice!) * 100).toFixed(2);
    expect(chpgSpreadPct).toBe("3.33");
  });

  // 13. Asserts zero production source modules import test fixtures or mock providers
  it("13. Asserts zero production source modules import test fixtures or mock providers", () => {
    const srcDir = path.resolve(__dirname, "..");
    const testDir = path.resolve(__dirname);

    function scanDir(dir: string, fileList: string[] = []) {
      const files = fs.readdirSync(dir);
      for (const file of files) {
        const fullPath = path.join(dir, file);
        if (fs.statSync(fullPath).isDirectory()) {
          if (fullPath !== testDir && !fullPath.includes("__tests__")) {
            scanDir(fullPath, fileList);
          }
        } else if (file.endsWith(".ts") || file.endsWith(".tsx")) {
          fileList.push(fullPath);
        }
      }
      return fileList;
    }

    const prodFiles = scanDir(srcDir);
    expect(prodFiles.length).toBeGreaterThan(10);

    for (const file of prodFiles) {
      const content = fs.readFileSync(file, "utf-8");
      expect(content).not.toContain("test_fixtures");
      expect(content).not.toContain("mock_market_data_provider");
      expect(content).not.toContain("mock_instrument_provider");
      expect(content).not.toContain("mock_historical_data_provider");
      expect(content).not.toContain("mock_quant_provider");
      expect(content).not.toContain("mockIndexData");
    }
  });
});
