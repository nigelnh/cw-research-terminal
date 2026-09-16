import { useEffect, useCallback, useMemo, useRef, useSyncExternalStore } from "react";
import { useQuery } from "@tanstack/react-query";
import type { WatchlistItem, ResearchWatchlist } from "@/domain/models";
import { defaultWatchlistStorage, DEFAULT_PRIMARY_WATCHLIST_ITEMS } from "@/domain/models";
import { SubscriptionPlanner, type SubscriptionPlan, type CanAddResult } from "@/data/subscription";
import { providers } from "@/data/providers";
import { config } from "@/config";
import { useAuth } from "@/data/auth";
import { useServerWatchlist } from "./use_server_watchlist";
import { backendClient } from "@/data/backend/backend_client";

const MANAGED_UNIVERSE_KEY = "cw-research:managed-universe:v1";

function itemSignature(items: WatchlistItem[]): string {
  return items.map(item => item.symbol.toUpperCase()).join("|");
}

function storedManagedSignature(scope: string): string | null {
  try {
    return window.localStorage?.getItem(`${MANAGED_UNIVERSE_KEY}:${scope}`) ?? null;
  } catch {
    return null;
  }
}

function rememberManagedSignature(scope: string, items: WatchlistItem[] | null): void {
  try {
    const key = `${MANAGED_UNIVERSE_KEY}:${scope}`;
    if (items) window.localStorage?.setItem(key, itemSignature(items));
    else window.localStorage?.removeItem(key);
  } catch {
    // Private mode or disabled storage: the render-session guards still apply.
  }
}

export function isManagedProductDefault(items: WatchlistItem[], scope: string): boolean {
  const symbols = itemSignature(items);
  const bundled = itemSignature(DEFAULT_PRIMARY_WATCHLIST_ITEMS);
  if (symbols === bundled && items.every(item => !item.notes)) return true;
  if (storedManagedSignature(scope) === symbols) return true;

  // Recover the managed marker on another browser after the first dynamic import. A
  // product universe has broad VN30/CW coverage; ordinary customized lists do not.
  const cwCount = items.filter(item => item.instrumentType === "CW").length;
  const stockCount = items.filter(item => item.instrumentType === "STOCK").length;
  return cwCount >= 100 && stockCount >= 20 && items.every(item => !item.notes);
}

// -------------------------------------------------------------------------- //
// Anonymous watchlist: single in-memory source of truth mirrored to versioned  //
// localStorage. Preserved exactly as-is for signed-out users AND kept intact   //
// while signed in, so signing out returns to a sensible anonymous list.        //
// -------------------------------------------------------------------------- //
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

export type WatchlistSource = "anonymous" | "server";

function buildItem(item: {
  symbol: string;
  instrumentType: "CW" | "STOCK" | "INDEX";
  underlyingSymbol?: string | null;
  notes?: string;
  // Callers may still pass contract fields (e.g. from a research-universe row); they are
  // intentionally ignored - contract terms are resolved live from the backend registry.
  issuer?: string | null;
  strikePrice?: number | null;
  exerciseRatio?: number | null;
  maturityDate?: string | null;
  lastTradingDate?: string | null;
}): WatchlistItem {
  return {
    symbol: item.symbol.toUpperCase(),
    instrumentType: item.instrumentType,
    underlyingSymbol: item.underlyingSymbol ? item.underlyingSymbol.toUpperCase() : null,
    addedAt: Date.now(),
    notes: item.notes,
  };
}

/**
 * The one watchlist hook. It RESOLVES a single canonical ordered list from whichever
 * source owns it - the anonymous localStorage store, or (when signed in) the PostgreSQL
 * server watchlist via TanStack Query - and exposes an identical surface either way.
 * `SubscriptionPlanner` and every consumer see only the resolved list.
 */
export function useWatchlist() {
  const provider = providers.marketData;
  const capabilities = useMemo(() => provider.getCapabilities(), [provider]);

  const anon = useSyncExternalStore(subscribeWatchlist, getWatchlistSnapshot, getWatchlistSnapshot);
  const server = useServerWatchlist();
  const { user } = useAuth();
  const { isActive: serverActive, isResolvedEmpty: serverEmpty, isLoading: serverLoading, isError: serverError, save: serverSave } =
    server;

  const source: WatchlistSource = serverActive ? "server" : "anonymous";
  const items: WatchlistItem[] = source === "server" ? server.items : anon.items;

  const universeQuery = useQuery({
    queryKey: ["instrument-default-universe", "current"],
    queryFn: ({ signal }) => backendClient.getDefaultUniverse(signal),
    staleTime: 30 * 60 * 1000,
    gcTime: 60 * 60 * 1000,
    retry: 2,
    refetchOnWindowFocus: false,
    refetchInterval: 15 * 60 * 1000,
    refetchIntervalInBackground: true,
  });
  const currentProductDefaults = useMemo<WatchlistItem[]>(() => {
    const rows = universeQuery.data?.items ?? [];
    return rows.map((row: any): WatchlistItem => ({
      symbol: String(row.symbol || "").toUpperCase(),
      instrumentType: row.instrument_type === "CW" ? "CW" : "STOCK",
      underlyingSymbol: row.underlying_symbol ? String(row.underlying_symbol).toUpperCase() : null,
      addedAt: 0,
    })).filter(row => !!row.symbol);
  }, [universeQuery.data]);

  // Danh sách 30 mã đóng gói chỉ dùng để bootstrap offline. Khi server công bố universe
  // VN30 + CW hiện hành, thay default chưa chỉnh sửa và giữ nguyên watchlist của người dùng.
  const defaultRefreshGuard = useRef<string | null>(null);
  useEffect(() => {
    if (serverActive || !currentProductDefaults.length) return;
    if (!isManagedProductDefault(anon.items, "anonymous")) return;
    const targetSignature = itemSignature(currentProductDefaults);
    if (itemSignature(anon.items) === targetSignature) {
      rememberManagedSignature("anonymous", currentProductDefaults);
      return;
    }
    if (defaultRefreshGuard.current === targetSignature) return;
    defaultRefreshGuard.current = targetSignature;
    rememberManagedSignature("anonymous", currentProductDefaults);
    emitWatchlistChange({ ...anon, items: currentProductDefaults, updatedAt: Date.now() });
  }, [serverActive, anon, currentProductDefaults]);

  const plan = useMemo<SubscriptionPlan>(
    () =>
      SubscriptionPlanner.computePlan(items, config.defaultLiveSymbols, capabilities.maxRealtimeSymbols),
    [items, capabilities.maxRealtimeSymbols]
  );

  // ONE provider subscription sync - independent of where the list came from.
  useEffect(() => {
    if (plan.requiredSymbols.length > 0) {
      if (typeof provider.syncSubscriptions === "function") {
        provider.syncSubscriptions(plan.requiredSymbols);
      } else {
        provider.subscribeSymbols(plan.requiredSymbols);
      }
    }
  }, [provider, plan.requiredSymbols]);

  // ---- First-login import (idempotent, once per subject) ------------------
  // server non-empty      -> server wins, no import
  // server empty + local  -> import the local ordered list
  // both empty            -> seed current product defaults
  const importGuardRef = useRef<string | null>(null);
  useEffect(() => {
    if (!serverActive || !user) return;
    if (serverLoading || serverError || !serverEmpty) return;
    if (importGuardRef.current === user.id) return;

    const flagKey = `cw-research:wl-import:${user.id}`;
    try {
      if (window.localStorage?.getItem(flagKey)) {
        importGuardRef.current = user.id;
        return;
      }
    } catch {
      /* private mode / disabled storage - fall through, ref still guards this session */
    }

    importGuardRef.current = user.id;
    const fallbackDefaults = anon.items.length > 0
      ? anon.items
      : [...DEFAULT_PRIMARY_WATCHLIST_ITEMS];
    const toImport = isManagedProductDefault(anon.items, "anonymous") && currentProductDefaults.length
      ? currentProductDefaults
      : fallbackDefaults;
    serverSave(toImport)
      .then(() => {
        if (itemSignature(toImport) === itemSignature(currentProductDefaults)) {
          rememberManagedSignature(`user:${user.id}`, currentProductDefaults);
        }
        try {
          window.localStorage?.setItem(flagKey, String(Date.now()));
        } catch {
          /* ignore */
        }
      })
      .catch(() => {
        importGuardRef.current = null; // allow a retry on the next render
      });
  }, [serverActive, serverEmpty, serverLoading, serverError, serverSave, user, anon.items, currentProductDefaults]);

  const serverDefaultRefreshGuard = useRef<string | null>(null);
  useEffect(() => {
    if (!serverActive || !user || serverLoading || serverError || serverEmpty) return;
    if (!currentProductDefaults.length || !isManagedProductDefault(server.items, `user:${user.id}`)) return;
    const targetSignature = itemSignature(currentProductDefaults);
    if (itemSignature(server.items) === targetSignature) {
      rememberManagedSignature(`user:${user.id}`, currentProductDefaults);
      return;
    }
    const guard = `${user.id}:${targetSignature}`;
    if (serverDefaultRefreshGuard.current === guard) return;
    serverDefaultRefreshGuard.current = guard;
    serverSave(currentProductDefaults)
      .then(() => rememberManagedSignature(`user:${user.id}`, currentProductDefaults))
      .catch(() => {
        serverDefaultRefreshGuard.current = null;
      });
  }, [serverActive, serverLoading, serverError, serverEmpty, server.items, serverSave, user, currentProductDefaults]);

  // ---- Mutations (routed to the active source) ---------------------------
  const commit = useCallback(
    (nextItems: WatchlistItem[]) => {
      if (source === "server") {
        if (user) rememberManagedSignature(`user:${user.id}`, null);
        void serverSave(nextItems);
      } else {
        rememberManagedSignature("anonymous", null);
        emitWatchlistChange({ ...anon, items: nextItems, updatedAt: Date.now() });
      }
    },
    [source, serverSave, anon, user]
  );

  const isInWatchlist = useCallback(
    (symbol: string): boolean => {
      const upper = symbol.toUpperCase();
      return items.some((item) => item.symbol.toUpperCase() === upper);
    },
    [items]
  );

  const canAdd = useCallback(
    (item: { symbol: string; instrumentType: string; underlyingSymbol?: string | null }): CanAddResult =>
      SubscriptionPlanner.canAddInstrument(plan, item),
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
      if (items.some((i) => i.symbol.toUpperCase() === sym)) {
        return { success: true };
      }
      const check = SubscriptionPlanner.canAddInstrument(plan, item);
      if (!check.allowed) {
        return { success: false, reason: check.reason };
      }
      commit([...items, buildItem(item)]);
      return { success: true };
    },
    [items, plan, commit]
  );

  const removeFromWatchlist = useCallback(
    (symbol: string): void => {
      const sym = symbol.toUpperCase();
      commit(items.filter((i) => i.symbol.toUpperCase() !== sym));
    },
    [items, commit]
  );

  const clearWatchlist = useCallback((): void => {
    commit([]);
  }, [commit]);

  const watchlist: ResearchWatchlist =
    source === "server" ? { ...anon, items, updatedAt: anon.updatedAt } : anon;

  return {
    watchlist,
    items,
    plan,
    capabilities,
    source,
    isSyncing: server.isActive && (server.isLoading || server.isSaving),
    isInWatchlist,
    canAdd,
    addToWatchlist,
    removeFromWatchlist,
    clearWatchlist,
  };
}
