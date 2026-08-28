import { describe, it, expect, beforeEach } from "vitest";
import {
  WatchlistStorage,
  WATCHLIST_STORAGE_KEY_V1,
  WATCHLIST_STORAGE_KEY_V2,
  CURRENT_WATCHLIST_SCHEMA_VERSION,
  type ResearchWatchlist,
} from "../domain/models/watchlist";
import { SubscriptionPlanner } from "../data/subscription/subscription_planner";

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

describe("WatchlistStorage Local Persistence, Versioned Migration & Resilience", () => {
  const TEST_KEY = "test_watchlist_v2";
  let storage: WatchlistStorage;
  let mockStorage: MemoryLocalStorage;

  beforeEach(() => {
    mockStorage = new MemoryLocalStorage();
    (globalThis as any).window = (globalThis as any).window || {};
    (globalThis as any).window.localStorage = mockStorage;
    storage = new WatchlistStorage(TEST_KEY);
  });

  it("1. Persisted v2 watchlist restores accurately across sessions", () => {
    const original: ResearchWatchlist = {
      id: "my_watchlist",
      name: "Quant Monitoring",
      items: [
        { symbol: "CHPG2541", instrumentType: "CW", underlyingSymbol: "HPG", addedAt: 100 },
        { symbol: "HPG", instrumentType: "STOCK", addedAt: 200 },
      ],
      createdAt: 100,
      updatedAt: 200,
      version: CURRENT_WATCHLIST_SCHEMA_VERSION,
    };

    storage.saveWatchlist(original);

    const loaded = storage.loadWatchlist();
    expect(loaded.id).toBe("my_watchlist");
    expect(loaded.name).toBe("Quant Monitoring");
    expect(loaded.items.length).toBe(2);
    expect(loaded.items[0].symbol).toBe("CHPG2541");
    expect(loaded.items[1].symbol).toBe("HPG");
    expect(loaded.version).toBe(CURRENT_WATCHLIST_SCHEMA_VERSION);
  });

  it("2. One-Time Migration: Migrates legacy V1 persisted watchlist to exact 5 primary symbols", () => {
    // Seed with the exact old persisted primary symbols under V1 storage
    const oldV1Payload = {
      id: "default_personal_watchlist",
      name: "My Personal Research Dashboard",
      items: [
        { symbol: "CFPT2602", instrumentType: "CW", underlyingSymbol: "FPT", addedAt: 1 },
        { symbol: "CHPG2602", instrumentType: "CW", underlyingSymbol: "HPG", addedAt: 2 },
        { symbol: "CFPT2604", instrumentType: "CW", underlyingSymbol: "FPT", addedAt: 3 },
        { symbol: "CHPG2611", instrumentType: "CW", underlyingSymbol: "HPG", addedAt: 4 },
        { symbol: "CHPG2609", instrumentType: "CW", underlyingSymbol: "HPG", addedAt: 5 },
        { symbol: "CHPG2604", instrumentType: "CW", underlyingSymbol: "HPG", addedAt: 6 },
      ],
      createdAt: 1000,
      updatedAt: 2000,
      version: 1,
    };

    mockStorage.setItem(WATCHLIST_STORAGE_KEY_V1, JSON.stringify(oldV1Payload));

    // Load with new V2 storage instance
    const defaultStorage = new WatchlistStorage(WATCHLIST_STORAGE_KEY_V2);
    const migrated = defaultStorage.loadWatchlist();

    // Assert exact 5 primary universe symbols
    expect(migrated.items.length).toBe(5);
    expect(migrated.items.map((i) => i.symbol)).toEqual(["HPG", "NVL", "VHM", "CVHM2615", "CHPG2541"]);
    expect(migrated.version).toBe(2);

    // Assert deduplicated realtime subscription planner output
    const plan = SubscriptionPlanner.computePlan(migrated.items, [], 33);
    expect(plan.requiredSymbols).toEqual(["CHPG2541", "CVHM2615", "HPG", "NVL", "VHM"]);
    expect(plan.symbolCount).toBe(5);

    // Assert old V1 key was cleaned up
    expect(mockStorage.getItem(WATCHLIST_STORAGE_KEY_V1)).toBeNull();
  });

  it("3. Reload after migration remains exactly 5 symbols without resetting", () => {
    // Migrate once
    const defaultStorage = new WatchlistStorage(WATCHLIST_STORAGE_KEY_V2);
    const firstLoad = defaultStorage.loadWatchlist();
    expect(firstLoad.items.length).toBe(5);

    // Second reload (e.g. page refresh)
    const secondLoad = defaultStorage.loadWatchlist();
    expect(secondLoad.items.length).toBe(5);
    expect(secondLoad.items.map((i) => i.symbol)).toEqual(["HPG", "NVL", "VHM", "CVHM2615", "CHPG2541"]);
  });

  it("4. Post-migration user edit persists across subsequent reloads", () => {
    const defaultStorage = new WatchlistStorage(WATCHLIST_STORAGE_KEY_V2);
    const current = defaultStorage.loadWatchlist();
    expect(current.items.length).toBe(5);

    // User adds a new instrument from Research (e.g. CFPT2601)
    const withUserAdd: ResearchWatchlist = {
      ...current,
      items: [
        ...current.items,
        { symbol: "CFPT2601", instrumentType: "CW", underlyingSymbol: "FPT", addedAt: Date.now() },
      ],
      updatedAt: Date.now(),
    };
    defaultStorage.saveWatchlist(withUserAdd);

    // Reload
    const reloaded = defaultStorage.loadWatchlist();
    expect(reloaded.items.length).toBe(6);
    expect(reloaded.items.map((i) => i.symbol)).toContain("CFPT2601");
  });

  it("5. Corrupt or malformed localStorage data fails safely to default 5 primary items", () => {
    mockStorage.setItem(TEST_KEY, "{ invalid json corrupt string");

    const loaded = storage.loadWatchlist();
    expect(loaded).toBeDefined();
    expect(loaded.items.length).toBe(5);
    expect(loaded.items.map((i) => i.symbol)).toEqual(["HPG", "NVL", "VHM", "CVHM2615", "CHPG2541"]);
    expect(loaded.version).toBe(CURRENT_WATCHLIST_SCHEMA_VERSION);
  });

  it("6. Handles non-array or null payloads gracefully", () => {
    mockStorage.setItem(TEST_KEY, JSON.stringify({ items: "not-an-array", version: 2 }));

    const loaded = storage.loadWatchlist();
    expect(loaded.items.length).toBe(5);
    expect(loaded.items.map((i) => i.symbol)).toEqual(["HPG", "NVL", "VHM", "CVHM2615", "CHPG2541"]);
  });

  it("7. Sanitizes corrupted watchlist item records in V2 payload", () => {
    mockStorage.setItem(
      TEST_KEY,
      JSON.stringify({
        items: [
          { symbol: "chpg2541", instrumentType: "COVERED_WARRANT", underlyingSymbol: "hpg" },
          { invalid: "no symbol" },
          null,
        ],
        version: CURRENT_WATCHLIST_SCHEMA_VERSION,
      })
    );

    const loaded = storage.loadWatchlist();
    expect(loaded.items.length).toBe(1);
    expect(loaded.items[0].symbol).toBe("CHPG2541");
    expect(loaded.items[0].instrumentType).toBe("CW");
    expect(loaded.items[0].underlyingSymbol).toBe("HPG");
  });
});
