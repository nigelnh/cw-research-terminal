import { describe, it, expect } from "vitest";
import { SubscriptionPlanner } from "../data/subscription/subscription_planner";
import type { WatchlistItem } from "../domain/models";

describe("SubscriptionPlanner & Dependency Reference Accounting", () => {
  it("1. Searching does not create a realtime subscription (empty watchlist produces only default symbols)", () => {
    const items: WatchlistItem[] = [];
    const plan = SubscriptionPlanner.computePlan(items, ["VNINDEX"], 33);

    expect(plan.explicitSymbols.size).toBe(0);
    expect(plan.dependencyMap.size).toBe(0);
    expect(plan.requiredSymbols).toEqual(["VNINDEX"]);
    expect(plan.symbolCount).toBe(1);
  });

  it("2. Adding a stock requires exactly one realtime symbol", () => {
    const items: WatchlistItem[] = [
      {
        symbol: "HPG",
        instrumentType: "STOCK",
        addedAt: Date.now(),
      },
    ];

    const plan = SubscriptionPlanner.computePlan(items, [], 33);
    expect(plan.requiredSymbols).toEqual(["HPG"]);
    expect(plan.symbolCount).toBe(1);
  });

  it("3. Adding a CW requires both the CW and its underlying stock", () => {
    const items: WatchlistItem[] = [
      {
        symbol: "CHPG2401",
        instrumentType: "CW",
        underlyingSymbol: "HPG",
        addedAt: Date.now(),
      },
    ];

    const plan = SubscriptionPlanner.computePlan(items, [], 33);
    expect(plan.requiredSymbols).toEqual(["CHPG2401", "HPG"]);
    expect(plan.symbolCount).toBe(2);
    expect(plan.dependencyMap.get("HPG")?.has("CHPG2401")).toBe(true);
  });

  it("4. Two CWs sharing the same underlying deduplicate the underlying", () => {
    const items: WatchlistItem[] = [
      { symbol: "CFPT2401", instrumentType: "CW", underlyingSymbol: "FPT", addedAt: 1 },
      { symbol: "CFPT2402", instrumentType: "CW", underlyingSymbol: "FPT", addedAt: 2 },
    ];

    const plan = SubscriptionPlanner.computePlan(items, [], 33);
    // CFPT2401, CFPT2402, FPT -> exactly 3 unique symbols (FPT counted once)
    expect(plan.requiredSymbols).toEqual(["CFPT2401", "CFPT2402", "FPT"]);
    expect(plan.symbolCount).toBe(3);
    expect(plan.dependencyMap.get("FPT")?.size).toBe(2);
  });

  it("5. Removing one of two CWs sharing an underlying preserves the underlying", () => {
    // Initial: 2 CWs on FPT
    const initialItems: WatchlistItem[] = [
      { symbol: "CFPT2401", instrumentType: "CW", underlyingSymbol: "FPT", addedAt: 1 },
      { symbol: "CFPT2402", instrumentType: "CW", underlyingSymbol: "FPT", addedAt: 2 },
    ];

    // Remove CFPT2401
    const nextItems = initialItems.filter((i) => i.symbol !== "CFPT2401");
    const plan = SubscriptionPlanner.computePlan(nextItems, [], 33);

    expect(plan.requiredSymbols).toEqual(["CFPT2402", "FPT"]);
    expect(plan.symbolCount).toBe(2);
    expect(plan.dependencyMap.get("FPT")?.has("CFPT2402")).toBe(true);
  });

  it("6. Removing the final dependent CW removes the automatic underlying subscription", () => {
    const items: WatchlistItem[] = [
      { symbol: "CFPT2401", instrumentType: "CW", underlyingSymbol: "FPT", addedAt: 1 },
    ];

    // Remove the only CW on FPT
    const nextItems = items.filter((i) => i.symbol !== "CFPT2401");
    const plan = SubscriptionPlanner.computePlan(nextItems, [], 33);

    expect(plan.requiredSymbols).toEqual([]);
    expect(plan.symbolCount).toBe(0);
    expect(plan.dependencyMap.has("FPT")).toBe(false);
  });

  it("7. An explicitly watched underlying survives removal of all dependent CWs", () => {
    const items: WatchlistItem[] = [
      { symbol: "CFPT2401", instrumentType: "CW", underlyingSymbol: "FPT", addedAt: 1 },
      { symbol: "FPT", instrumentType: "STOCK", addedAt: 2 }, // Explicitly watched stock
    ];

    // Remove the CW
    const nextItems = items.filter((i) => i.symbol !== "CFPT2401");
    const plan = SubscriptionPlanner.computePlan(nextItems, [], 33);

    expect(plan.requiredSymbols).toEqual(["FPT"]);
    expect(plan.explicitSymbols.has("FPT")).toBe(true);
    expect(plan.symbolCount).toBe(1);
  });

  it("8. Capacity calculation uses unique symbols including default benchmark indices", () => {
    const items: WatchlistItem[] = [
      { symbol: "CFPT2401", instrumentType: "CW", underlyingSymbol: "FPT", addedAt: 1 },
      { symbol: "CFPT2402", instrumentType: "CW", underlyingSymbol: "FPT", addedAt: 2 },
      { symbol: "HPG", instrumentType: "STOCK", addedAt: 3 },
    ];

    const plan = SubscriptionPlanner.computePlan(items, ["VNINDEX", "VN30"], 33);
    // VNINDEX, VN30, CFPT2401, CFPT2402, FPT, HPG -> 6 symbols
    expect(plan.symbolCount).toBe(6);
    expect(plan.remainingCapacity).toBe(27);
    expect(plan.isCapacityExceeded).toBe(false);
  });

  it("9. Provider realtime capacity is strictly enforced without silent eviction", () => {
    const items: WatchlistItem[] = [
      { symbol: "CFPT2401", instrumentType: "CW", underlyingSymbol: "FPT", addedAt: 1 },
    ]; // requires CFPT2401, FPT, plus VNINDEX = 3 slots

    const plan = SubscriptionPlanner.computePlan(items, ["VNINDEX"], 3);
    expect(plan.symbolCount).toBe(3);

    // Attempting to add a new CW requiring new symbols CHPG2401 and HPG (2 additional)
    const checkNew = SubscriptionPlanner.canAddInstrument(plan, {
      symbol: "CHPG2401",
      instrumentType: "CW",
      underlyingSymbol: "HPG",
    });

    expect(checkNew.allowed).toBe(false);
    expect(checkNew.additionalSymbols).toEqual(["CHPG2401", "HPG"]);
    expect(checkNew.reason).toContain("requires 2 additional live subscriptions");

    // Attempting to add another CW on FPT (requires only 1 additional slot for CFPT2402 because FPT is shared)
    const checkShared = SubscriptionPlanner.canAddInstrument(plan, {
      symbol: "CFPT2402",
      instrumentType: "CW",
      underlyingSymbol: "FPT",
    });

    expect(checkShared.allowed).toBe(false);
    expect(checkShared.additionalSymbols).toEqual(["CFPT2402"]);
    expect(checkShared.reason).toContain("requires 1 additional live subscription");
  });

  it("10. Adding instrument is allowed when within capacity limit", () => {
    const items: WatchlistItem[] = [];
    const plan = SubscriptionPlanner.computePlan(items, ["VNINDEX"], 33);

    const check = SubscriptionPlanner.canAddInstrument(plan, {
      symbol: "CHPG2401",
      instrumentType: "CW",
      underlyingSymbol: "HPG",
    });

    expect(check.allowed).toBe(true);
    expect(check.additionalSymbols).toEqual(["CHPG2401", "HPG"]);
    expect(check.projectedUsage).toBe(3); // VNINDEX + CHPG2401 + HPG
  });
});
