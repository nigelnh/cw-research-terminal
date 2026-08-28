import { describe, it, expect, beforeEach } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { PersonalDashboard } from "../features/watchlist/personal_dashboard";
import { createDefaultWatchlist, defaultWatchlistStorage } from "../domain/models/watchlist";
import { resetWatchlistMemoryForTests } from "../data/watchlist/use_watchlist";
import { mapRawSnapshotToCoveredWarrant, mapRawSnapshotToQuote } from "../data/backend/mappers/map_snapshot";
import { applyRawPatchToQuote } from "../data/backend/mappers/map_patch";

class MemoryStorage {
  private store: Record<string, string> = {};

  getItem(key: string): string | null {
    return this.store[key] !== undefined ? this.store[key] : null;
  }

  setItem(key: string, value: string): void {
    this.store[key] = String(value);
  }

  removeItem(key: string): void {
    delete this.store[key];
  }

  clear(): void {
    this.store = {};
  }
}

describe("Targeted Frontend Regression Restore & Reconciliation", () => {
  let mockStorage: MemoryStorage;

  beforeEach(() => {
    mockStorage = new MemoryStorage();
    (globalThis as any).window = (globalThis as any).window || {};
    (globalThis as any).window.localStorage = mockStorage;

    const fresh = createDefaultWatchlist();
    defaultWatchlistStorage.saveWatchlist(fresh);
    resetWatchlistMemoryForTests(fresh);
  });

  it("1, 2, 3, 4. Dashboard contains Stocks (3) [HPG, NVL, VHM] and Covered Warrants (2) [CVHM2615, CHPG2541]", () => {
    const html = renderToStaticMarkup(<PersonalDashboard />);

    // Section 1: Stocks (3)
    expect(html).toContain("Stocks (3)");
    expect(html).toContain("HPG");
    expect(html).toContain("NVL");
    expect(html).toContain("VHM");

    // Section 2: Covered Warrants (2)
    expect(html).toContain("Covered Warrants (2)");
    expect(html).toContain("CVHM2615");
    expect(html).toContain("CHPG2541");

    // Must NOT say Covered Warrants (5)
    expect(html).not.toContain("Covered Warrants (5)");
  });

  it("5. Stocks never render CW ratio/strike/DTE/IV columns", () => {
    const html = renderToStaticMarkup(<PersonalDashboard />);
    const stocksSection = html.split("Covered Warrants")[0];

    // Stocks section table must only have stock headers
    expect(stocksSection).toContain("Symbol");
    expect(stocksSection).toContain("Ref");
    expect(stocksSection).toContain("Bid");
    expect(stocksSection).toContain("Ask");
    expect(stocksSection).toContain("Last");
    expect(stocksSection).toContain("Chg");
    expect(stocksSection).toContain("Volume");

    // Must NOT contain CW headers in stocks section
    expect(stocksSection).not.toContain("Und. price");
    expect(stocksSection).not.toContain("Strike");
    expect(stocksSection).not.toContain("Ratio");
    expect(stocksSection).not.toContain("DTE");
    expect(stocksSection).not.toContain("IV bid");
  });

  it("6. Missing exercise ratio does not default to 1:1 or 1.0", () => {
    const rawNoRatio = {
      Symbol: "CHPG2541",
      Under_Symbol: "HPG",
      Traded: 0.30,
      Bid1_Prc: 0.29,
      Ask1_Prc: 0.30,
    };
    const mappedCw = mapRawSnapshotToCoveredWarrant(rawNoRatio);
    expect(mappedCw.exerciseRatio).toBeNull();
  });

  it("7. CHPG2541 BidAsk maps from backend to frontend accurately in raw VND", () => {
    const rawPatch = {
      Symbol: "CHPG2541",
      Bid1_Prc: 0.29, // 290 VND
      Ask1_Prc: 0.30, // 300 VND
      Bid1_Qty: 100,
      Ask1_Qty: 100,
    };

    const quote = applyRawPatchToQuote(undefined, "CHPG2541", rawPatch);
    expect(quote.bidPrice).toBe(290);
    expect(quote.askPrice).toBe(300);
    expect(quote.bidQuantity).toBe(100);
    expect(quote.askQuantity).toBe(100);
  });

  it("8 & 9. Real zero remains zero, missing trade/last price remains null/em-dash, and absence of event is not faked", () => {
    const rawNoTrade = {
      Symbol: "CVHM2615",
      Bid1_Prc: 1.83,
      Ask1_Prc: 1.86,
    };
    const quote = mapRawSnapshotToQuote(rawNoTrade);

    expect(quote.bidPrice).toBe(1830);
    expect(quote.askPrice).toBe(1860);
    expect(quote.lastPrice).toBeNull(); // Missing trade remains null
    expect(quote.totalVolume).toBeNull();
  });
});
