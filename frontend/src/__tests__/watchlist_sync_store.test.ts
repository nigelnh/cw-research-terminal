import { describe, it, expect, beforeEach } from "vitest";
import {
  subscribeWatchlist,
  getWatchlistSnapshot,
  emitWatchlistChange,
  resetWatchlistMemoryForTests,
} from "../data/watchlist/use_watchlist";
import { defaultWatchlistStorage, createDefaultWatchlist } from "../domain/models/watchlist";
import { SubscriptionPlanner } from "../data/subscription/subscription_planner";

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

describe("Watchlist useSyncExternalStore Synchronization & Store Integrity", () => {
  let mockStorage: MemoryLocalStorage;

  beforeEach(() => {
    mockStorage = new MemoryLocalStorage();
    (globalThis as any).window = (globalThis as any).window || {};
    (globalThis as any).window.localStorage = mockStorage;

    const fresh = createDefaultWatchlist();
    defaultWatchlistStorage.saveWatchlist(fresh);
    resetWatchlistMemoryForTests(fresh);
  });

  it("1. getSnapshot returns a stable reference when state is unchanged", () => {
    const snap1 = getWatchlistSnapshot();
    const snap2 = getWatchlistSnapshot();
    expect(snap1).toBe(snap2); // Strict reference equality
  });

  it("2. Two independent subscribers receive state updates simultaneously and immediately", () => {
    let subscriber1Received: any = null;
    let subscriber2Received: any = null;

    const unsub1 = subscribeWatchlist(() => {
      subscriber1Received = getWatchlistSnapshot();
    });

    const unsub2 = subscribeWatchlist(() => {
      subscriber2Received = getWatchlistSnapshot();
    });

    const nextState = {
      ...getWatchlistSnapshot(),
      items: [
        {
          symbol: "CFPT2401",
          instrumentType: "CW" as const,
          underlyingSymbol: "FPT",
          addedAt: Date.now(),
        },
      ],
      updatedAt: Date.now(),
    };

    emitWatchlistChange(nextState);

    expect(subscriber1Received).toBe(nextState);
    expect(subscriber2Received).toBe(nextState);
    expect(subscriber1Received.items.length).toBe(1);
    expect(subscriber2Received.items[0].symbol).toBe("CFPT2401");

    unsub1();
    unsub2();
  });

  it("3. Remove propagates immediately to all active subscribers", () => {
    // Seed with 2 items
    const seeded = {
      ...getWatchlistSnapshot(),
      items: [
        { symbol: "CFPT2401", instrumentType: "CW" as const, underlyingSymbol: "FPT", addedAt: 1 },
        { symbol: "CHPG2401", instrumentType: "CW" as const, underlyingSymbol: "HPG", addedAt: 2 },
      ],
    };
    emitWatchlistChange(seeded);

    let notificationCount = 0;
    const unsub = subscribeWatchlist(() => {
      notificationCount++;
    });

    // Remove CFPT2401
    const afterRemoval = {
      ...getWatchlistSnapshot(),
      items: getWatchlistSnapshot().items.filter((i) => i.symbol !== "CFPT2401"),
      updatedAt: Date.now(),
    };
    emitWatchlistChange(afterRemoval);

    expect(notificationCount).toBe(1);
    const current = getWatchlistSnapshot();
    expect(current.items.length).toBe(1);
    expect(current.items[0].symbol).toBe("CHPG2401");

    unsub();
  });

  it("4. Realtime subscription plan slot counts compute synchronously upon state changes", () => {
    let plan = SubscriptionPlanner.computePlan(getWatchlistSnapshot().items, ["VNINDEX"], 33);
    expect(plan.symbolCount).toBe(1); // Only default VNINDEX

    // Add CW (requires CW + Underlying FPT)
    const withCW = {
      ...getWatchlistSnapshot(),
      items: [
        { symbol: "CFPT2401", instrumentType: "CW" as const, underlyingSymbol: "FPT", addedAt: 1 },
      ],
    };
    emitWatchlistChange(withCW);

    plan = SubscriptionPlanner.computePlan(getWatchlistSnapshot().items, ["VNINDEX"], 33);
    expect(plan.symbolCount).toBe(3); // VNINDEX + CFPT2401 + FPT
    expect(plan.requiredSymbols).toContain("CFPT2401");
    expect(plan.requiredSymbols).toContain("FPT");

    // Add second CW on SAME underlying (deduplicates FPT)
    const withSecondCW = {
      ...getWatchlistSnapshot(),
      items: [
        ...getWatchlistSnapshot().items,
        { symbol: "CFPT2402", instrumentType: "CW" as const, underlyingSymbol: "FPT", addedAt: 2 },
      ],
    };
    emitWatchlistChange(withSecondCW);

    plan = SubscriptionPlanner.computePlan(getWatchlistSnapshot().items, ["VNINDEX"], 33);
    expect(plan.symbolCount).toBe(4); // VNINDEX + CFPT2401 + CFPT2402 + FPT (only 1 additional slot consumed)
  });

  it("5. Persisted localStorage state matches in-memory snapshot after changes", () => {
    const updated = {
      ...getWatchlistSnapshot(),
      items: [
        { symbol: "FPT", instrumentType: "STOCK" as const, addedAt: 500 },
      ],
      updatedAt: 500,
    };
    emitWatchlistChange(updated);

    const fromStorage = defaultWatchlistStorage.loadWatchlist();
    expect(fromStorage.items.length).toBe(1);
    expect(fromStorage.items[0].symbol).toBe("FPT");
    expect(fromStorage.updatedAt).toBeGreaterThan(0);
  });

  it("6. Subscriber cleanup / unmount does not leak or receive stale notifications", () => {
    let callCount = 0;
    const unsubscribe = subscribeWatchlist(() => {
      callCount++;
    });

    emitWatchlistChange({ ...getWatchlistSnapshot(), updatedAt: 10 });
    expect(callCount).toBe(1);

    // Unsubscribe (simulate component unmount)
    unsubscribe();

    emitWatchlistChange({ ...getWatchlistSnapshot(), updatedAt: 20 });
    emitWatchlistChange({ ...getWatchlistSnapshot(), updatedAt: 30 });
    expect(callCount).toBe(1); // No further invocations
  });
});
