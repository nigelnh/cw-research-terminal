import { describe, it, expect, beforeEach } from "vitest";
import { renderMarkup, seedInstrumentSpecs } from "./test_fixtures/render_markup";
import { PersonalDashboard } from "../features/watchlist/personal_dashboard";
import { defaultWatchlistStorage } from "../domain/models/watchlist";
import { resetWatchlistMemoryForTests } from "../data/watchlist/use_watchlist";

class MemoryStorage {
  private store: Record<string, string> = {};
  getItem(key: string) { return this.store[key] ?? null; }
  setItem(key: string, value: string) { this.store[key] = String(value); }
  removeItem(key: string) { delete this.store[key]; }
  clear() { this.store = {}; }
}

/** A watchlist that holds one CW - IDENTITY ONLY (v3 shape). */
function watchlistWith(symbol: string, underlyingSymbol: string) {
  return {
    id: "wl", name: "wl",
    items: [{ symbol, instrumentType: "CW" as const, underlyingSymbol, addedAt: 0 }],
    createdAt: 0, updatedAt: 0, version: 3,
  };
}

describe("Dashboard contract metadata comes from the canonical registry, not the watchlist item", () => {
  beforeEach(() => {
    const s = new MemoryStorage();
    (globalThis as any).window = (globalThis as any).window || {};
    (globalThis as any).window.localStorage = s;
  });

  it("registry PARTIAL -> 'partial' badge, contract terms em-dash", () => {
    const wl = watchlistWith("CVPB2615", "VPB");
    defaultWatchlistStorage.saveWatchlist(wl);
    resetWatchlistMemoryForTests(wl);

    const html = renderMarkup(<PersonalDashboard />, [
      seedInstrumentSpecs([
        { symbol: "CVPB2615", issuer: "ACBS", underlyingSymbol: "VPB",
          strikePrice: null, exerciseRatio: null, dataQuality: "PARTIAL", metadataVerification: "UNVERIFIED" },
      ]),
    ]);

    expect(html).toContain("CVPB2615");
    expect(html).toContain("partial");
    expect(html).not.toContain("conflicting");
  });

  it("registry COMPLETE + VERIFIED_CURRENT -> no 'partial', shows canonical strike/ratio", () => {
    const wl = watchlistWith("CVPB2615", "VPB");
    defaultWatchlistStorage.saveWatchlist(wl);
    resetWatchlistMemoryForTests(wl);

    const html = renderMarkup(<PersonalDashboard />, [
      seedInstrumentSpecs([
        { symbol: "CVPB2615", issuer: "ACBS", underlyingSymbol: "VPB",
          strikePrice: 28500, exerciseRatio: 2, maturityDate: "2027-02-17", lastTradingDate: "2027-02-15",
          dataQuality: "COMPLETE", metadataVerification: "VERIFIED_CURRENT" },
      ]),
    ]);

    expect(html).toContain("CVPB2615");
    expect(html).toContain("ACBS");
    expect(html).toContain("28,500");
    expect(html).toContain("2:1");
    expect(html).not.toContain("partial");
    expect(html).not.toContain("conflicting");
  });

  it("registry CONFLICTING -> 'conflicting' badge, as-issued terms still shown", () => {
    const wl = watchlistWith("CTCB2601", "TCB");
    defaultWatchlistStorage.saveWatchlist(wl);
    resetWatchlistMemoryForTests(wl);

    const html = renderMarkup(<PersonalDashboard />, [
      seedInstrumentSpecs([
        { symbol: "CTCB2601", issuer: "ACBS", underlyingSymbol: "TCB",
          strikePrice: 37000, exerciseRatio: 4, maturityDate: "2026-10-26", lastTradingDate: "2026-10-22",
          dataQuality: "COMPLETE", metadataVerification: "CONFLICTING" },
      ]),
    ]);

    expect(html).toContain("CTCB2601");
    expect(html).toContain("conflicting");
    expect(html).toContain("37,000");
    expect(html).toContain("4:1");
  });

  it("a STALE watchlist item cannot override the canonical registry (KIS/25,000 -> ACBS/37,000)", () => {
    // Simulate a pre-correction persisted item that still carries frozen KIS / 25,000 / 2:1.
    const wl = {
      id: "wl", name: "wl",
      items: [{
        symbol: "CTCB2601", instrumentType: "CW" as const, underlyingSymbol: "TCB",
        issuer: "KIS", strikePrice: 25000, exerciseRatio: 2, maturityDate: "2026-12-10", addedAt: 0,
      }],
      createdAt: 0, updatedAt: 0, version: 3,
    };
    defaultWatchlistStorage.saveWatchlist(wl as any);
    resetWatchlistMemoryForTests(wl as any);

    const html = renderMarkup(<PersonalDashboard />, [
      seedInstrumentSpecs([
        { symbol: "CTCB2601", issuer: "ACBS", underlyingSymbol: "TCB",
          strikePrice: 37000, exerciseRatio: 4, maturityDate: "2026-10-26", lastTradingDate: "2026-10-22",
          dataQuality: "COMPLETE", metadataVerification: "CONFLICTING" },
      ]),
    ]);

    expect(html).toContain("ACBS");
    expect(html).toContain("37,000");
    expect(html).toContain("4:1");
    expect(html).not.toContain("KIS");
    expect(html).not.toContain("25,000");
  });
});
