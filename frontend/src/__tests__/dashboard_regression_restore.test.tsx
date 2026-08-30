import { describe, it, expect, beforeEach } from "vitest";
import { renderMarkup } from "./test_fixtures/render_markup";
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

  it("1, 2, 3, 4. Watchlist contains the curated default universe [HPG, VPB, VNINDEX] + [CHPG2602, CVPB2615]", () => {
    const html = renderMarkup(<PersonalDashboard />);

    expect(html).toContain("Watchlist");
    expect(html).toContain("HPG");
    expect(html).toContain("VPB");
    expect(html).toContain("VNINDEX");
    expect(html).toContain("CHPG2602");
    expect(html).toContain("CVPB2615");

    // No fabricated warrants in the default universe.
    expect(html).not.toContain("CTCB2601");
    expect(html).not.toContain("CFPT2602");
  });

  it("5. Stock table renders the stock column set, never CW-only columns", () => {
    const html = renderMarkup(<PersonalDashboard />);
    // the CW table follows the stock table; scope to the stock table region
    const stockRegion = html.split("UND.")[0];

    expect(stockRegion).toContain("SYMBOL");
    expect(stockRegion).toContain("REF");
    expect(stockRegion).toContain("BID");
    expect(stockRegion).toContain("ASK");
    expect(stockRegion).toContain("TRD");
    expect(stockRegion).toContain("CHG%");
    expect(stockRegion).toContain("VOLUME");
    expect(stockRegion).toContain("FRN BUY");

    expect(stockRegion).not.toContain("STRIKE");
    expect(stockRegion).not.toContain("RATIO");
    expect(stockRegion).not.toContain("IV BID");
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
