import type { WatchlistItem } from "@/domain/models";

export interface SubscriptionPlan {
  explicitSymbols: Set<string>;
  dependencyMap: Map<string, Set<string>>; // underlyingSymbol -> Set of CW symbols referencing it
  defaultSymbols: Set<string>;
  requiredSymbols: string[]; // Deduplicated, sorted list of all unique symbols requiring realtime ticks
  symbolCount: number;
  capacity: number | null; // null represents unlimited capacity
  isCapacityExceeded: boolean;
  remainingCapacity: number | null;
}

export interface CanAddResult {
  allowed: boolean;
  additionalSymbols: string[];
  currentUsage: number;
  maxCapacity: number | null;
  projectedUsage: number;
  reason?: string;
}

/**
 * SubscriptionPlanner
 * 
 * Pure, deterministic planner that computes the unique realtime symbol set
 * from a user's personal watchlist and default market symbols.
 * 
 * Invariants:
 * 1. Adding a stock requires 1 symbol (the stock itself).
 * 2. Adding a CW requires 2 symbols (the CW + its underlying stock).
 * 3. Shared underlyings across multiple CWs are automatically deduplicated.
 * 4. Removing a CW does NOT remove its underlying if other watched CWs or explicit stock items still depend on it.
 * 5. Provider capacity limits the personal realtime dashboard, NEVER search or research discovery.
 */
export class SubscriptionPlanner {
  public static computePlan(
    watchlistItems: WatchlistItem[],
    defaultSymbols: string[] = [],
    maxCapacity: number | null = 33
  ): SubscriptionPlan {
    const explicitSymbols = new Set<string>();
    const dependencyMap = new Map<string, Set<string>>();
    const defaultSet = new Set<string>();

    // 1. Ingest default always-on symbols (e.g. VNINDEX, VN30)
    defaultSymbols.forEach((s) => {
      if (s && s.trim()) {
        defaultSet.add(s.trim().toUpperCase());
      }
    });

    // 2. Ingest explicitly watched instruments and their underlying dependencies
    watchlistItems.forEach((item) => {
      const sym = item.symbol.toUpperCase();
      explicitSymbols.add(sym);

      if ((item.instrumentType === "CW" || item.instrumentType === ("COVERED_WARRANT" as any)) && item.underlyingSymbol) {
        const underlying = item.underlyingSymbol.toUpperCase();
        if (!dependencyMap.has(underlying)) {
          dependencyMap.set(underlying, new Set());
        }
        dependencyMap.get(underlying)!.add(sym);
      }
    });

    // 3. Compute unique unified set of required live symbols
    const uniqueSymbols = new Set<string>([
      ...defaultSet,
      ...explicitSymbols,
      ...dependencyMap.keys(),
    ]);

    const requiredSymbols = Array.from(uniqueSymbols).sort();
    const symbolCount = requiredSymbols.length;
    const isCapacityExceeded = maxCapacity !== null && symbolCount > maxCapacity;
    const remainingCapacity = maxCapacity !== null ? Math.max(0, maxCapacity - symbolCount) : null;

    return {
      explicitSymbols,
      dependencyMap,
      defaultSymbols: defaultSet,
      requiredSymbols,
      symbolCount,
      capacity: maxCapacity,
      isCapacityExceeded,
      remainingCapacity,
    };
  }

  /**
   * Evaluates if a new instrument can be added without exceeding provider capacity.
   * If capacity is exceeded, returns a detailed explanation of the additional symbols required.
   */
  public static canAddInstrument(
    currentPlan: SubscriptionPlan,
    item: { symbol: string; instrumentType: string; underlyingSymbol?: string | null }
  ): CanAddResult {
    const sym = item.symbol.toUpperCase();
    const currentRequired = new Set(currentPlan.requiredSymbols);
    const additionalSymbols: string[] = [];

    // Check if the instrument symbol itself is already subscribed
    if (!currentRequired.has(sym)) {
      additionalSymbols.push(sym);
    }

    // If it's a CW, check if its underlying symbol is already subscribed
    const isCW = item.instrumentType === "CW" || item.instrumentType === "COVERED_WARRANT";
    if (isCW && item.underlyingSymbol) {
      const underlying = item.underlyingSymbol.toUpperCase();
      if (!currentRequired.has(underlying) && !additionalSymbols.includes(underlying)) {
        additionalSymbols.push(underlying);
      }
    }

    const currentUsage = currentPlan.symbolCount;
    const projectedUsage = currentUsage + additionalSymbols.length;
    const maxCapacity = currentPlan.capacity;

    if (maxCapacity !== null && projectedUsage > maxCapacity) {
      const reason = additionalSymbols.length === 1
        ? `Adding ${sym} requires 1 additional live subscription (${additionalSymbols.join(", ")}). ${currentUsage} / ${maxCapacity} realtime slots are currently in use.`
        : `Adding ${sym} requires ${additionalSymbols.length} additional live subscriptions (${additionalSymbols.join(", ")}). ${currentUsage} / ${maxCapacity} realtime slots are currently in use.`;

      return {
        allowed: false,
        additionalSymbols,
        currentUsage,
        maxCapacity,
        projectedUsage,
        reason,
      };
    }

    return {
      allowed: true,
      additionalSymbols,
      currentUsage,
      maxCapacity,
      projectedUsage,
    };
  }
}
