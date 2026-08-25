/**
 * Web Worker for handling WebSocket communication and data processing
 */

import { WSClient } from "./ws_client";

let wsClient: WSClient | null = null;
const patchBuffer = new Map<string, { patch: any; ts?: number }>();
const snapshotBuffer = new Map<string, { row: any; ts?: number }>(); 

// Source of truth in the worker
const rowsMap = new Map<string, any>();
const lastFlushedRowsMap = new Map<string, any>();
// Buffer for tick-by-tick directions to avoid "net change" color errors
const pendingDirections = new Map<string, "up" | "down">();

function propagateDirection(sym: string, key: string, dir: "up" | "down") {
  pendingDirections.set(`${sym}:${key}`, dir);
  
  if (key === "Bid1_Prc") {
    pendingDirections.set(`${sym}:Bid1_Qty`, dir);
    const row = rowsMap.get(sym);
    if (row && row.Vol1 > 0 && row.Vol3 > 0) {
      pendingDirections.set(`${sym}:Spread`, dir);
    }
  } else if (key === "Ask1_Prc") {
    pendingDirections.set(`${sym}:Ask1_Qty`, dir);
    const row = rowsMap.get(sym);
    if (row && row.Vol1 > 0 && row.Vol3 > 0) {
      pendingDirections.set(`${sym}:Spread`, dir);
    }
  } else if (key === "Vol3" || key === "Vol1") {
    const row = rowsMap.get(sym);
    if (row && row.Vol1 > 0 && row.Vol3 > 0) {
      pendingDirections.set(`${sym}:Spread`, dir);
    }
  } else if (key === "Traded") {
    pendingDirections.set(`${sym}:Traded_Qty`, dir);
    pendingDirections.set(`${sym}:Change`, dir);
    pendingDirections.set(`${sym}:ChangePercent`, dir);
  }
}

function handleSnapshot(symbol: string, row: any, ts?: number) {
  const sym = symbol.toUpperCase();
  snapshotBuffer.set(sym, { row, ts });
  
  const existing = rowsMap.get(sym) || {};
  const updatedRow = { ...existing, ...row, _ts: ts || Date.now() };
  rowsMap.set(sym, updatedRow);

  Object.entries(row).forEach(([key, newVal]) => {
    if (typeof newVal === 'number') {
      const oldVal = existing[key];
      if (oldVal !== undefined && oldVal !== null && newVal !== oldVal) {
        propagateDirection(sym, key, newVal > oldVal ? "up" : "down");
      }
    }
  });

  self.postMessage({ type: "INSTANT_SNAPSHOT", symbol: sym, row: updatedRow, ts });
}

function handlePatch(symbol: string, patch: any, ts?: number) {
  const sym = symbol.toUpperCase();
  const existingPatch = patchBuffer.get(sym)?.patch || {};
  patchBuffer.set(sym, { patch: { ...existingPatch, ...patch }, ts });
  
  const row = rowsMap.get(sym) || { Symbol: sym };
  const updatedRow = { ...row, ...patch, _ts: ts || Date.now() };
  rowsMap.set(sym, updatedRow);

  Object.entries(patch).forEach(([key, newVal]) => {
    if (typeof newVal === 'number') {
      const oldVal = (row as any)[key];
      if (oldVal !== undefined && oldVal !== null && newVal !== oldVal) {
        propagateDirection(sym, key, newVal > oldVal ? "up" : "down");
      }
    }
  });

  self.postMessage({ type: "INSTANT_PATCH", symbol: sym, patch, row: updatedRow, ts });
}

function handleStatusChange(connected: boolean, message: string) {
  self.postMessage({ type: "STATUS", connected, message });
}

function handleIndexUpdate(data: any, ts: number) {
  self.postMessage({ type: "INDEX_UPDATE", data, ts });
}

function handleTradingDates(dates: string[]) {
  self.postMessage({ type: "TRADING_DATES", dates });
}

function handleListedVolumes(date: string, volumes: Record<string, number>) {
  self.postMessage({ type: "LISTED_VOLUMES", date, volumes });
}

// Periodically flush updates for the full list
let lastStructuralFlush = 0;

setInterval(() => {
  const now = Date.now();
  if (patchBuffer.size === 0 && snapshotBuffer.size === 0) return;

  // Symbols that actually changed in this window
  const changedSymbols = new Set([...patchBuffer.keys(), ...snapshotBuffer.keys()]);

  patchBuffer.clear();
  snapshotBuffer.clear();

  const changes: [string, "up" | "down"][] = [];
  
  // 1. Add changes from pending directions (most accurate for high-freq ticks)
  pendingDirections.forEach((dir, key) => {
    changes.push([key, dir]);
  });
  pendingDirections.clear();

  // Structural flush check (only if symbol count changes or initial flush)
  // Must be checked BEFORE updating lastFlushedRowsMap for new symbols in the loop below
  const isInitialFlush = lastStructuralFlush === 0;
  const shouldFlushStructural = isInitialFlush || rowsMap.size > lastFlushedRowsMap.size;

  // 2. Fallback: Calculate changes for symbols that changed but didn't have a clear direction 
  // (e.g. first time appearing, or complex snapshots)
  changedSymbols.forEach((symbol) => {
    const row = rowsMap.get(symbol);
    const prevRow = lastFlushedRowsMap.get(symbol);
    
    if (row && prevRow) {
      Object.entries(row).forEach(([key, newVal]) => {
        // Skip internal or non-numeric fields for flash comparison
        if (key.startsWith("_") || typeof newVal === "string") return;
        
        const cellKey = `${symbol}:${key}`;
        // If already added from pendingDirections, skip
        if (changes.some(c => c[0] === cellKey)) return;

        const oldVal = prevRow[key];
        const oldNum = typeof oldVal === "number" ? oldVal : (oldVal === null || oldVal === undefined ? NaN : parseFloat(String(oldVal)));
        const newNum = typeof newVal === "number" ? newVal : (newVal === null || newVal === undefined ? NaN : parseFloat(String(newVal)));

        const isOldZeroOrNull = isNaN(oldNum) || oldNum === 0;
        const isNewZeroOrNull = isNaN(newNum) || newNum === 0;

        if (isOldZeroOrNull && !isNewZeroOrNull) {
            propagateDirection(symbol, key, "up");
        } else if (!isOldZeroOrNull && isNewZeroOrNull) {
            propagateDirection(symbol, key, "down");
        }
      });
    }
    
    // Crucial: Update the comparison map for this symbol so we don't flash again next time 
    // unless a NEW change arrives.
    if (row) {
      lastFlushedRowsMap.set(symbol, { ...row });
    }
  });

  // Send the flushed state update to main thread
  self.postMessage({ 
    type: "FLUSH", 
    rows: shouldFlushStructural ? Array.from(rowsMap.values()) : null,
    changes: changes,
    dirtySymbols: Array.from(changedSymbols), // Optimized: Tell main thread which rows need hydration
    ts: now
  });

  if (shouldFlushStructural) {
    lastStructuralFlush = now;
    // For structural flushes, ensure all rows are in the comparison map
    rowsMap.forEach((v, k) => {
      if (!lastFlushedRowsMap.has(k)) lastFlushedRowsMap.set(k, { ...v });
    });
  }
}, 50); 

self.onmessage = (e) => {
  const { type, url, payload } = e.data;

  switch (type) {
    case "CONNECT":
      if (wsClient) wsClient.disconnect();
      wsClient = new WSClient(url, {
        onSnapshot: handleSnapshot,
        onPatch: handlePatch,
        onStatusChange: handleStatusChange,
        onIndexUpdate: handleIndexUpdate,
        onTradingDates: handleTradingDates,
        onListedVolumes: handleListedVolumes,
      });
      wsClient.connect();
      break;

    case "DISCONNECT":
      if (wsClient) {
        wsClient.disconnect();
        wsClient = null;
      }
      break;

    case "SEND":
      if (wsClient) {
        wsClient.send(payload);
      }
      break;
  }
};
