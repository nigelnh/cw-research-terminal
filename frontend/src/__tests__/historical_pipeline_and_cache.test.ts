import { describe, it, expect, beforeEach, vi } from "vitest";
import {
  HistoricalDataCache,
  getHistoricalCacheKey,
  HISTORICAL_CACHE_PREFIX,
  type HistoricalCacheRecord,
} from "../data/historical/historical_data_cache";
import { BackendHistoricalDataProvider } from "../data/backend/backend_historical_data_provider";
import type { BackendClient } from "../data/backend/backend_client";

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

  get length(): number {
    return Object.keys(this.store).length;
  }

  key(index: number): string | null {
    const keys = Object.keys(this.store);
    return keys[index] !== undefined ? keys[index] : null;
  }

  clear(): void {
    this.store = {};
  }
}

describe("Targeted Historical Data Pipeline + Local Cache Verifications", () => {
  let mockStorage: MemoryStorage;

  beforeEach(() => {
    mockStorage = new MemoryStorage();
    (globalThis as any).window = (globalThis as any).window || {};
    (globalThis as any).window.localStorage = mockStorage;
  });

  it("1 & 11. HPG historical endpoint returns normalized rows with Raw VND values preserved", async () => {
    const mockClient = {
      getMarketHistory: vi.fn().mockResolvedValue([
        { date: "2026-08-25", open: 22250.0, high: 22300.0, low: 21800.0, close: 21800.0, volume: 25890640.0, adjusted: true },
        { date: "2026-08-24", open: 22000.0, high: 22300.0, low: 21850.0, close: 22250.0, volume: 28836994.0, adjusted: true },
      ]),
    } as unknown as BackendClient;

    const provider = new BackendHistoricalDataProvider(mockClient);
    const bars = await provider.getHistoricalBars("HPG", "3M");

    expect(bars).toHaveLength(2);
    expect(bars[0].close).toBe(21800.0);
    expect(bars[0].open).toBe(22250.0);
    // Preserves Raw VND without artificial scale-down
    expect(bars[0].close).toBeGreaterThan(1000);

    // Verify written to localStorage cache
    const cachedKey = getHistoricalCacheKey("HPG", "daily_1y");
    const raw = mockStorage.getItem(cachedKey);
    expect(raw).toBeTruthy();
    const record: HistoricalCacheRecord = JSON.parse(raw!);
    expect(record.rows[0].close).toBe(21800.0);
  });

  it("2 & 3. Historical data loads during LUNCH_BREAK and quote_display_eligible=false does not block history", async () => {
    const mockClient = {
      getMarketHistory: vi.fn().mockResolvedValue([
        { date: "2026-08-25", open: 22250.0, high: 22300.0, low: 21800.0, close: 21800.0, volume: 1000.0 },
      ]),
    } as unknown as BackendClient;

    const provider = new BackendHistoricalDataProvider(mockClient);
    // isTradingActive = false represents lunch break or closed market
    const bars = await provider.getHistoricalBars("HPG", "3M", true, false);

    expect(bars).toHaveLength(1);
    expect(mockClient.getMarketHistory).toHaveBeenCalledTimes(1);
  });

  it("4 & 5. 3M default reads daily_1y and 1M -> 3M -> 6M -> 1Y navigation reuses the single daily_1y fetch", async () => {
    const rows = [];
    for (let i = 1; i <= 200; i++) {
      const date = new Date(Date.now() - (200 - i) * 86400000).toISOString().split("T")[0];
      rows.push({ date, open: 20000 + i, high: 20500 + i, low: 19900 + i, close: 20200 + i, volume: 10000 });
    }

    const mockClient = {
      getMarketHistory: vi.fn().mockResolvedValue(rows),
    } as unknown as BackendClient;

    const provider = new BackendHistoricalDataProvider(mockClient);

    // 1. Initial 3M fetch
    const bars3M = await provider.getHistoricalBars("HPG", "3M");
    expect(bars3M.length).toBeGreaterThan(0);
    expect(mockClient.getMarketHistory).toHaveBeenCalledTimes(1);

    // 2. Subsequent 1M view -> reuses cache, 0 new backend calls
    const bars1M = await provider.getHistoricalBars("HPG", "1M");
    expect(bars1M.length).toBeLessThanOrEqual(bars3M.length);
    expect(mockClient.getMarketHistory).toHaveBeenCalledTimes(1);

    // 3. Subsequent 6M view -> reuses cache, 0 new backend calls
    const bars6M = await provider.getHistoricalBars("HPG", "6M");
    expect(bars6M.length).toBeGreaterThanOrEqual(bars3M.length);
    expect(mockClient.getMarketHistory).toHaveBeenCalledTimes(1);

    // 4. Subsequent 1Y view -> reuses cache, 0 new backend calls
    const bars1Y = await provider.getHistoricalBars("HPG", "1Y");
    expect(bars1Y.length).toBe(200);
    expect(mockClient.getMarketHistory).toHaveBeenCalledTimes(1);
  });

  it("6 & 7. 1D uses intraday_1d and 5D uses intraday_5d datasets", async () => {
    const mockClient = {
      getMarketHistory: vi.fn().mockImplementation((_sym, tf) => {
        if (tf === "5m") {
          return Promise.resolve([{ date: "2026-08-25 14:45", open: 21800, high: 21800, low: 21800, close: 21800, volume: 100 }]);
        }
        if (tf === "30m") {
          return Promise.resolve([{ date: "2026-08-25 14:30", open: 21800, high: 21800, low: 21800, close: 21800, volume: 500 }]);
        }
        return Promise.resolve([]);
      }),
    } as unknown as BackendClient;

    const provider = new BackendHistoricalDataProvider(mockClient);

    const bars1D = await provider.getHistoricalBars("HPG", "1D");
    expect(bars1D).toHaveLength(1);
    expect(mockClient.getMarketHistory).toHaveBeenCalledWith("HPG", "5m", undefined, undefined, true);

    const bars5D = await provider.getHistoricalBars("HPG", "5D");
    expect(bars5D).toHaveLength(1);
    expect(mockClient.getMarketHistory).toHaveBeenCalledWith("HPG", "30m", undefined, undefined, true);
  });

  it("8 & 9. Cache survives browser reload and restores without issuing a new vendor request", async () => {
    // Seed existing valid cache in localStorage
    const now = Date.now();
    const cachedRecord: HistoricalCacheRecord = {
      schema_version: 1,
      symbol: "HPG",
      dataset: "daily_1y",
      interval: "1d",
      adjusted: true,
      fetched_at: now,
      data_through: "2026-08-25",
      rows: [
        { date: "2026-08-24", open: 22000, high: 22300, low: 21850, close: 22250, volume: 1000 },
        { date: "2026-08-25", open: 22250, high: 22300, low: 21800, close: 21800, volume: 1000 },
      ],
    };

    mockStorage.setItem(getHistoricalCacheKey("HPG", "daily_1y"), JSON.stringify(cachedRecord));

    const mockClient = {
      getMarketHistory: vi.fn(),
    } as unknown as BackendClient;

    const provider = new BackendHistoricalDataProvider(mockClient);
    const bars = await provider.getHistoricalBars("HPG", "3M");

    expect(bars).toHaveLength(2);
    expect(bars[1].close).toBe(21800);
    // Zero backend calls made
    expect(mockClient.getMarketHistory).not.toHaveBeenCalled();
  });

  it("10. Duplicate simultaneous requests for same symbol/dataset are coalesced into a single request", async () => {
    let callCount = 0;
    const mockClient = {
      getMarketHistory: vi.fn().mockImplementation(async () => {
        callCount++;
        await new Promise((r) => setTimeout(r, 20));
        return [{ date: "2026-08-25", open: 22000, high: 22000, low: 22000, close: 22000, volume: 1000 }];
      }),
    } as unknown as BackendClient;

    const provider = new BackendHistoricalDataProvider(mockClient);

    // Run 3 simultaneous requests for HPG 3M
    const [res1, res2, res3] = await Promise.all([
      provider.getHistoricalBars("HPG", "3M"),
      provider.getHistoricalBars("HPG", "3M"),
      provider.getHistoricalBars("HPG", "3M"),
    ]);

    expect(res1).toHaveLength(1);
    expect(res2).toHaveLength(1);
    expect(res3).toHaveLength(1);
    expect(callCount).toBe(1);
  });

  it("12. Missing history returns empty array and is not converted to zero prices", async () => {
    const mockClient = {
      getMarketHistory: vi.fn().mockResolvedValue([]),
    } as unknown as BackendClient;

    const provider = new BackendHistoricalDataProvider(mockClient);
    const bars = await provider.getHistoricalBars("EMPTY_SYM", "3M");

    expect(bars).toEqual([]);
  });

  it("13 & 14. Rate limit with valid cache returns cached history; rate limit with no cache safely throws or returns empty", async () => {
    // 1. With cache
    const cachedRecord: HistoricalCacheRecord = {
      schema_version: 1,
      symbol: "HPG",
      dataset: "daily_1y",
      interval: "1d",
      adjusted: true,
      fetched_at: Date.now() - 3600000,
      data_through: "2026-08-25",
      rows: [{ date: "2026-08-25", open: 22000, high: 22000, low: 22000, close: 22000, volume: 1000 }],
    };
    mockStorage.setItem(getHistoricalCacheKey("HPG", "daily_1y"), JSON.stringify(cachedRecord));

    const failingClient = {
      getMarketHistory: vi.fn().mockRejectedValue(new Error("Rate limit reached")),
    } as unknown as BackendClient;

    const provider = new BackendHistoricalDataProvider(failingClient);
    const fallbackBars = await provider.getHistoricalBars("HPG", "3M");
    expect(fallbackBars).toHaveLength(1);
    expect(fallbackBars[0].close).toBe(22000);

    // 2. Without cache
    await expect(provider.getHistoricalBars("NOCACHE_SYM", "3M")).rejects.toThrow("Rate limit reached");
  });

  it("15 & 18. Cache eviction bounds capacity to MAX_CACHED_SYMBOLS and strictly preserves non-historical keys", () => {
    // Set watchlists and copilot chats
    mockStorage.setItem("cw-watchlist-v2", JSON.stringify(["HPG", "VHM"]));
    mockStorage.setItem("cw_research:copilot_history:v2", JSON.stringify({ version: 2 }));

    // Add 25 historical cache items
    for (let i = 1; i <= 25; i++) {
      HistoricalDataCache.set(`SYM_${i}`, "daily_1y", [
        { date: "2026-08-25", open: 1000, high: 1000, low: 1000, close: 1000, volume: 100 },
      ]);
    }

    // Verify non-historical keys are completely untouched
    expect(mockStorage.getItem("cw-watchlist-v2")).toBeTruthy();
    expect(mockStorage.getItem("cw_research:copilot_history:v2")).toBeTruthy();

    // Verify historical symbol count is bounded
    let histCount = 0;
    for (let i = 0; i < mockStorage.length; i++) {
      const k = mockStorage.key(i);
      if (k && k.startsWith(HISTORICAL_CACHE_PREFIX)) {
        histCount++;
      }
    }
    expect(histCount).toBeLessThanOrEqual(20);
  });
});
