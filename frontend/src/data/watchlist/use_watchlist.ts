import { useEffect, useCallback, useMemo, useSyncExternalStore } from "react";
import type { WatchlistItem, ResearchWatchlist } from "@/domain/models";
import { defaultWatchlistStorage } from "@/domain/models";
import { SubscriptionPlanner, type SubscriptionPlan, type CanAddResult } from "@/data/subscription";
import { providers } from "@/data/providers";
import { config } from "@/config";

// Single Source of Truth in memory synced with localStorage
let memoryWatchlist: ResearchWatchlist = defaultWatchlistStorage.loadWatchlist();
const listeners = new Set<() => void>();

export function subscribeWatchlist(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function getWatchlistSnapshot(): ResearchWatchlist {
  return memoryWatchlist;
}

export function emitWatchlistChange(next: ResearchWatchlist) {
  memoryWatchlist = next;
  defaultWatchlistStorage.saveWatchlist(next);
  listeners.forEach((l) => l());
}

export function resetWatchlistMemoryForTests(initial?: ResearchWatchlist) {
  memoryWatchlist = initial || defaultWatchlistStorage.loadWatchlist();
  listeners.forEach((l) => l());
}

export function useWatchlist() {
  const provider = providers.marketData;
  const capabilities = useMemo(() => provider.getCapabilities(), [provider]);

  // Synchronized across all components via useSyncExternalStore
  const watchlist = useSyncExternalStore(subscribeWatchlist, getWatchlistSnapshot, getWatchlistSnapshot);

  // Calculate deterministic subscription plan
  const plan = useMemo<SubscriptionPlan>(() => {
    return SubscriptionPlanner.computePlan(
      watchlist.items,
      config.defaultLiveSymbols,
      capabilities.maxRealtimeSymbols
    );
  }, [watchlist.items, capabilities.maxRealtimeSymbols]);

  // Synchronize desired live symbols to active market data provider
  useEffect(() => {
    if (plan.requiredSymbols.length > 0) {
      provider.subscribeSymbols(plan.requiredSymbols);
    }
  }, [provider, plan.requiredSymbols]);

  const isInWatchlist = useCallback(
    (symbol: string): boolean => {
      const upper = symbol.toUpperCase();
      return watchlist.items.some((item: WatchlistItem) => item.symbol.toUpperCase() === upper);
    },
    [watchlist.items]
  );

  const canAdd = useCallback(
    (item: { symbol: string; instrumentType: string; underlyingSymbol?: string | null }): CanAddResult => {
      return SubscriptionPlanner.canAddInstrument(plan, item);
    },
    [plan]
  );

  const addToWatchlist = useCallback(
    (item: {
      symbol: string;
      instrumentType: "CW" | "STOCK" | "INDEX";
      underlyingSymbol?: string | null;
      issuer?: string | null;
      strikePrice?: number | null;
      exerciseRatio?: number | null;
      maturityDate?: string | null;
      lastTradingDate?: string | null;
      notes?: string;
    }): { success: boolean; reason?: string } => {
      const sym = item.symbol.toUpperCase();

      // 1. Idempotency: If already in watchlist, treat as success
      if (watchlist.items.some((i: WatchlistItem) => i.symbol.toUpperCase() === sym)) {
        return { success: true };
      }

      // 2. Capacity Check: Enforce max realtime slots
      const check = SubscriptionPlanner.canAddInstrument(plan, item);
      if (!check.allowed) {
        return { success: false, reason: check.reason };
      }

      // 3. Create canonical item and emit change to all subscribers
      const newItem: WatchlistItem = {
        symbol: sym,
        instrumentType: item.instrumentType,
        underlyingSymbol: item.underlyingSymbol ? item.underlyingSymbol.toUpperCase() : null,
        issuer: item.issuer || null,
        strikePrice: item.strikePrice || null,
        exerciseRatio: item.exerciseRatio || null,
        maturityDate: item.maturityDate || null,
        lastTradingDate: item.lastTradingDate || null,
        addedAt: Date.now(),
        notes: item.notes,
      };

      const updatedWatchlist: ResearchWatchlist = {
        ...watchlist,
        items: [...watchlist.items, newItem],
        updatedAt: Date.now(),
      };

      emitWatchlistChange(updatedWatchlist);
      return { success: true };
    },
    [watchlist, plan]
  );

  const removeFromWatchlist = useCallback(
    (symbol: string): void => {
      const sym = symbol.toUpperCase();
      const nextItems = watchlist.items.filter((i: WatchlistItem) => i.symbol.toUpperCase() !== sym);

      const updatedWatchlist: ResearchWatchlist = {
        ...watchlist,
        items: nextItems,
        updatedAt: Date.now(),
      };

      emitWatchlistChange(updatedWatchlist);
    },
    [watchlist]
  );

  const clearWatchlist = useCallback((): void => {
    const emptyWatchlist: ResearchWatchlist = {
      ...watchlist,
      items: [],
      updatedAt: Date.now(),
    };
    emitWatchlistChange(emptyWatchlist);
  }, [watchlist]);

  return {
    watchlist,
    items: watchlist.items,
    plan,
    capabilities,
    isInWatchlist,
    canAdd,
    addToWatchlist,
    removeFromWatchlist,
    clearWatchlist,
  };
}
