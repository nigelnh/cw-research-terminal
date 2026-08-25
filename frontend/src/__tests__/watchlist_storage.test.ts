import { describe, it, expect, beforeEach } from "vitest";
import { WatchlistStorage, type ResearchWatchlist } from "../domain/models/watchlist";

// Memory LocalStorage Mock for isolated unit testing
class MemoryLocalStorage {
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

describe("WatchlistStorage Local Persistence & Resilience", () => {
  const TEST_KEY = "test_watchlist_v1";
  let storage: WatchlistStorage;
  let mockStorage: MemoryLocalStorage;

  beforeEach(() => {
    mockStorage = new MemoryLocalStorage();
    (globalThis as any).window = (globalThis as any).window || {};
    (globalThis as any).window.localStorage = mockStorage;
    storage = new WatchlistStorage(TEST_KEY);
  });

  it("11. Persisted watchlist restores accurately across sessions", () => {
    const original: ResearchWatchlist = {
      id: "my_watchlist",
      name: "Quant Monitoring",
      items: [
        { symbol: "CHPG2602", instrumentType: "CW", underlyingSymbol: "HPG", addedAt: 100 },
        { symbol: "FPT", instrumentType: "STOCK", addedAt: 200 },
      ],
      createdAt: 100,
      updatedAt: 200,
      version: 1,
    };

    storage.saveWatchlist(original);

    const loaded = storage.loadWatchlist();
    expect(loaded.id).toBe("my_watchlist");
    expect(loaded.name).toBe("Quant Monitoring");
    expect(loaded.items.length).toBe(2);
    expect(loaded.items[0].symbol).toBe("CHPG2602");
    expect(loaded.items[1].symbol).toBe("FPT");
  });

  it("12. Corrupt or malformed localStorage data fails safely to default watchlist", () => {
    mockStorage.setItem(TEST_KEY, "{ invalid json corrupt string");

    const loaded = storage.loadWatchlist();
    expect(loaded).toBeDefined();
    expect(loaded.items).toEqual([]);
    expect(loaded.version).toBe(1);
  });

  it("13. Handles non-array or null payloads gracefully", () => {
    mockStorage.setItem(TEST_KEY, JSON.stringify({ items: "not-an-array" }));

    const loaded = storage.loadWatchlist();
    expect(loaded.items).toEqual([]);
  });

  it("14. Sanitizes corrupted watchlist item records", () => {
    mockStorage.setItem(
      TEST_KEY,
      JSON.stringify({
        items: [
          { symbol: "chpg2401", instrumentType: "COVERED_WARRANT", underlyingSymbol: "hpg" },
          { invalid: "no symbol" },
          null,
        ],
      })
    );

    const loaded = storage.loadWatchlist();
    expect(loaded.items.length).toBe(1);
    expect(loaded.items[0].symbol).toBe("CHPG2401");
    expect(loaded.items[0].instrumentType).toBe("CW");
    expect(loaded.items[0].underlyingSymbol).toBe("HPG");
  });
});
