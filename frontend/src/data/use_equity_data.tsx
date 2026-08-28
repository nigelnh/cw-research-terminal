/**
 * React Context and Provider for equity data with realtime updates
 */

import { createContext, useContext, useEffect, useRef, useState, useCallback, ReactNode } from "react";
import type { EquityRow } from "@/tables/equity/types";
import { config } from "@/config";
import type { IndexRow } from "@/tables/index/types";

const WS_URL = config.wsUrl;

interface EquityDataContextValue {
  rows: EquityRow[];
  indices: IndexRow[];
  connected: boolean;
  statusMessage: string;
  tradingDates: string[];
  requestListedVolumes: (date: string) => void;
  listedVolumes: Record<string, number>;
  lastChanges: Map<string, "up" | "down">;
  serverTimeOffset: number;
  // New subscription for unbuffered real-time updates
  subscribeSymbol: (symbol: string | null | undefined, callback: (row: EquityRow) => void) => () => void;
  // Get row data by symbol without triggering a full context re-render
  getRow: (symbol: string | null | undefined) => EquityRow | undefined;
  // Live value access (replaces SharedArrayBuffer)
  getNumericValue: (symbol: string | null | undefined, field: string) => number | null;
  isSymbolDirty: (symbol: string | null | undefined) => boolean;
  lastUpdateTs: number;
}

const EquityDataContext = createContext<EquityDataContextValue | undefined>(undefined);

export function EquityDataProvider({ children }: { children: ReactNode }) {
  const [rows, setRows] = useState<EquityRow[]>([]);
  const [indices, setIndices] = useState<IndexRow[]>([]);
  const [connected, setConnected] = useState(false);
  const [statusMessage, setStatusMessage] = useState("Connecting...");
  const [tradingDates, setTradingDates] = useState<string[]>([]);
  const [listedVolumes, setListedVolumes] = useState<Record<string, number>>({});
  const [lastChanges, setLastChanges] = useState<Map<string, "up" | "down">>(new Map());
  const [serverTimeOffset, setServerTimeOffset] = useState(0);
  const [lastUpdateTs, setLastUpdateTs] = useState(0);
  
  const workerRef = useRef<Worker | null>(null);
  const rowsRef = useRef<EquityRow[]>([]);
  const rowsMapRef = useRef<Map<string, EquityRow>>(new Map());
  const dirtySymbolsRef = useRef<Set<string>>(new Set());

  // Read live numeric values directly from the in-memory row map.
  // rowsMapRef is kept up-to-date on every FLUSH tick (~50ms), which is
  // more than sufficient for sorting and row hydration.
  const getNumericValue = useCallback((symbol: string | null | undefined, field: string): number | null => {
    if (!symbol) return null;
    const row = rowsMapRef.current.get(symbol.toUpperCase()) as any;
    if (!row) return null;
    const val = row[field];
    return typeof val === 'number' ? val : null;
  }, []);
  const lastServerTimeUpdateRef = useRef<number>(0);
  
  const isSymbolDirty = useCallback((symbol: string | null | undefined) => {
    if (!symbol) return false;
    return dirtySymbolsRef.current.has(symbol.toUpperCase());
  }, []);

  // High-frequency listeners for priority symbols (e.g. charts)
  const listenersRef = useRef<Map<string, Set<(row: EquityRow) => void>>>(new Map());

  const subscribeSymbol = useCallback((symbol: string | null | undefined, callback: (row: EquityRow) => void) => {
    if (!symbol) return () => {};
    const sym = symbol.toUpperCase();
    if (!listenersRef.current.has(sym)) {
      listenersRef.current.set(sym, new Set());
    }
    listenersRef.current.get(sym)!.add(callback);
    
    // Return unsubscribe function
    return () => {
      const callbacks = listenersRef.current.get(sym);
      if (callbacks) {
        callbacks.delete(callback);
        if (callbacks.size === 0) listenersRef.current.delete(sym);
      }
    };
  }, []);

  const getRow = useCallback((symbol: string | null | undefined) => {
    if (!symbol) return undefined;
    return rowsMapRef.current.get(symbol.toUpperCase());
  }, []);

  const triggerListeners = useCallback((symbol: string | null | undefined, row: EquityRow | IndexRow, ts?: number) => {
    if (!symbol) return;
    const sym = symbol.toUpperCase();
    const callbacks = listenersRef.current.get(sym);
    
    // Trigger primary listener
    if (callbacks && callbacks.size > 0) {
      const isIndexRow = (row as IndexRow).name !== undefined && (row as any).Symbol === undefined;

      let payload: any;
      if (isIndexRow) {
        payload = { ...(row as IndexRow), _ts: ts || Date.now() };
      } else {
        const existing = rowsMapRef.current.get(sym) || { Symbol: sym } as EquityRow;
        payload = { ...existing, ...(row as EquityRow), _ts: ts || Date.now() };
      }

      callbacks.forEach(cb => cb(payload));
    }
  }, []);

  // Keep rowsRef and rowsMapRef in sync with the latest rows state.
  useEffect(() => {
    rowsRef.current = rows;
    const newMap = new Map<string, EquityRow>();
    rows.forEach(r => {
      newMap.set(r.Symbol, r);
    });
    rowsMapRef.current = newMap;
  }, [rows]);

  const updateServerTime = useCallback((ts: number) => {
    const now = Date.now();
    // Update at most once every 10 seconds to avoid unnecessary re-renders
    if (now - lastServerTimeUpdateRef.current > 10000) {
      setServerTimeOffset(ts - now);
      lastServerTimeUpdateRef.current = now;
    }
  }, []);

  const handleIndexUpdate = useCallback((data: IndexRow, ts: number) => {
    if (ts) updateServerTime(ts);
    const sym = data.name.toUpperCase();
    setIndices((prev) => {
      const next = [...prev];
      const idx = next.findIndex((r) => r.name.toUpperCase() === sym);
      if (idx !== -1) next[idx] = { ...data, name: sym };
      else next.push({ ...data, name: sym });
      return next;
    });
    // Trigger listeners for index (using its uppercase name as the symbol)
    triggerListeners(sym, { ...data, name: sym } as any, ts);
  }, [updateServerTime, triggerListeners]);

  const requestListedVolumes = useCallback((date: string) => {
    workerRef.current?.postMessage({ type: "SEND", payload: { type: "request_listed_volumes", date } });
  }, []);

  useEffect(() => {
    // Instantiate worker
    const worker = new Worker(new URL("./wsWorker.ts", import.meta.url), { type: "module" });
    workerRef.current = worker;

    worker.onmessage = (e) => {
      const { type, symbol, row, patch, connected, message, data, ts, dates, volumes, rows: nextRows, changes } = e.data;

      switch (type) {
        case "INSTANT_SNAPSHOT":
          if (ts) updateServerTime(ts);
          rowsMapRef.current.set(symbol.toUpperCase(), row);
          triggerListeners(symbol, row, ts);
          break;

        case "INSTANT_PATCH":
          if (ts) updateServerTime(ts);
          {
            const sym = symbol.toUpperCase();
            // Use the full updated row from the worker if available, 
            // otherwise merge with existing or create a new entry.
            const updatedRow = row || { ...rowsMapRef.current.get(sym), ...patch, Symbol: sym };
            rowsMapRef.current.set(sym, updatedRow);
          }
          triggerListeners(symbol, (row || patch) as any, ts);
          break;

        case "STATUS":
          setConnected(connected);
          setStatusMessage(message);
          break;

        case "INDEX_UPDATE":
          handleIndexUpdate(data, ts);
          break;

        case "TRADING_DATES":
          setTradingDates(dates);
          break;

        case "LISTED_VOLUMES":
          setListedVolumes(volumes);
          break;

        case "FLUSH":
          if (nextRows) {
            const newMap = new Map<string, EquityRow>();
            nextRows.forEach((r: EquityRow) => newMap.set(r.Symbol, r));
            rowsMapRef.current = newMap;
            setRows(nextRows);
          }
          
          if (changes) {
            const changesMap = new Map<string, "up" | "down">();
            changes.forEach(([k, v]: [string, "up" | "down"]) => changesMap.set(k, v));
            setLastChanges(changesMap);
          }

          if (e.data.dirtySymbols) {
             dirtySymbolsRef.current = new Set(e.data.dirtySymbols);
          }

          // Atomic synchronization: remove inconsistent 66ms throttle.
          // The worker already regulates this at 50ms. By updating lastUpdateTs
          // every time a flush arrives, we guarantee the TableRow hydration 
          // happens in the same render as the lastChanges flash trigger.
          const nowFlush = Date.now();
          setLastUpdateTs(ts || nowFlush);
          break;
      }
    };

    worker.postMessage({ type: "CONNECT", url: WS_URL });

    return () => {
      worker.postMessage({ type: "DISCONNECT" });
      worker.terminate();
    };
  }, [WS_URL, handleIndexUpdate, triggerListeners, updateServerTime]);

  const value = {
    rows,
    indices,
    connected,
    statusMessage,
    tradingDates,
    requestListedVolumes,
    listedVolumes,
    lastChanges,
    serverTimeOffset,
    subscribeSymbol,
    getRow,
    getNumericValue,
    isSymbolDirty,
    lastUpdateTs,
  };

  return (
    <EquityDataContext.Provider value={value}>
      {children}
    </EquityDataContext.Provider>
  );
}

export function useEquityData() {
  const context = useContext(EquityDataContext);
  if (context === undefined) {
    throw new Error("useEquityData must be used within an EquityDataProvider");
  }
  return context;
}
