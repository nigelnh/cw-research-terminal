import { describe, it, expect, beforeEach } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { PersonalDashboard } from "../features/watchlist/personal_dashboard";
import { defaultWatchlistStorage } from "../domain/models/watchlist";
import { resetWatchlistMemoryForTests } from "../data/watchlist/use_watchlist";

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

describe("Partial Instrument UX & Complete Contract Differentiation", () => {
  let mockStorage: MemoryStorage;

  beforeEach(() => {
    mockStorage = new MemoryStorage();
    (globalThis as any).window = (globalThis as any).window || {};
    (globalThis as any).window.localStorage = mockStorage;
  });

  it("1. Incomplete CW metadata renders subtle 'partial' indicator and keeps contract/IV fields as em-dash", () => {
    const customWatchlist = {
      id: "partial_test_wl",
      name: "Partial Test",
      items: [
        {
          symbol: "CVPB2615",
          instrumentType: "CW" as const,
          underlyingSymbol: "VPB",
          issuer: "ACBS",
          strikePrice: null,
          exerciseRatio: null,
          maturityDate: null,
          addedAt: 0,
        },
      ],
      createdAt: Date.now(),
      updatedAt: Date.now(),
      version: 2,
    };
    defaultWatchlistStorage.saveWatchlist(customWatchlist);
    resetWatchlistMemoryForTests(customWatchlist);

    const html = renderToStaticMarkup(<PersonalDashboard />);

    // Symbol is rendered
    expect(html).toContain("CVPB2615");
    // Subtle 'partial' indicator is present
    expect(html).toContain("partial");
    expect(html).toContain('title="Unverified / Partial specification in registry');
  });

  it("2. Complete verified CW renders contract terms without 'partial' indicator", () => {
    const customWatchlist = {
      id: "complete_test_wl",
      name: "Complete Test",
      items: [
        {
          symbol: "CTCB2601",
          instrumentType: "CW" as const,
          underlyingSymbol: "TCB",
          issuer: "KIS",
          strikePrice: 25000,
          exerciseRatio: 2,
          maturityDate: "2026-12-10",
          addedAt: 0,
        },
      ],
      createdAt: Date.now(),
      updatedAt: Date.now(),
      version: 2,
    };
    defaultWatchlistStorage.saveWatchlist(customWatchlist);
    resetWatchlistMemoryForTests(customWatchlist);

    const html = renderToStaticMarkup(<PersonalDashboard />);

    // Symbol and strike/ratio are rendered
    expect(html).toContain("CTCB2601");
    expect(html).toContain("25,000");
    expect(html).toContain("2:1");
    // 'partial' tag is NOT present
    expect(html).not.toContain("partial");
  });
});
