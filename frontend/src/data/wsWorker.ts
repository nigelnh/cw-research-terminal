/**
 * Web Worker for handling WebSocket communication and data processing
 */

import { WSClient } from "./wsClient";

let wsClient: WSClient | null = null;
const patchBuffer = new Map<string, { patch: any; ts?: number }>();
const snapshotBuffer = new Map<string, { row: any; ts?: number }>(); 

// Source of truth in the worker
const rowsMap = new Map<string, any>();
const lastFlushedRowsMap = new Map<string, any>();
const underlyingToCWs = new Map<string, Set<string>>();

// Buffer for tick-by-tick directions to avoid "net change" color errors
const pendingDirections = new Map<string, "up" | "down">();

function isAfter915AM() {
  const now = new Date();
  // Vietnam is UTC+7
  const utcMinutes = now.getUTCHours() * 60 + now.getUTCMinutes();
  const vnMinutes = (utcMinutes + 7 * 60) % (24 * 60);
  return vnMinutes >= (9 * 60 + 15);
}

function propagateDirection(sym: string, key: string, dir: "up" | "down") {
  const row = rowsMap.get(sym);
  const isMarketOpen = isAfter915AM();

  // Basic flash for the column itself
  // Requirement: Under_Prc and Under_Symbol don't flash before 9:15 AM.
  if (isMarketOpen || (key !== "Under_Prc" && key !== "Under_Symbol")) {
     pendingDirections.set(`${sym}:${key}`, dir);
  }
  
  if (key === "Bid1_Prc") {
    pendingDirections.set(`${sym}:Bid1_Qty`, dir);
    // Requirement 2 from first request: Spread(%) flashes if both Vol_Bid1 and Vol_Ask1 have values
    if (row && row.Vol1 > 0 && row.Vol3 > 0) {
      pendingDirections.set(`${sym}:Spread`, dir);
    }
  } else if (key === "Ask1_Prc") {
    pendingDirections.set(`${sym}:Ask1_Qty`, dir);
    if (row && row.Vol1 > 0 && row.Vol3 > 0) {
      pendingDirections.set(`${sym}:Spread`, dir);
    }
  } else if (key === "Vol3" || key === "Vol1") { // Vol changed naturally
    if (row && row.Vol1 > 0 && row.Vol3 > 0) {
      pendingDirections.set(`${sym}:Spread`, dir);
    }
  } else if (key === "Traded") {
    pendingDirections.set(`${sym}:Traded_Qty`, dir);
    pendingDirections.set(`${sym}:Change`, dir);
    pendingDirections.set(`${sym}:ChangePercent`, dir);
  } else if (key === "Under_Prc") {
    pendingDirections.set(`${sym}:Under_Symbol`, dir);
    // Requirement: Spread doesn't flash if triggered by Under_Prc changes BEFORE 9:15 AM.
    if (isMarketOpen) {
      if (row && row.Vol1 > 0 && row.Vol3 > 0) {
        pendingDirections.set(`${sym}:Spread`, dir);
      }
    }
  }
}

function handleSnapshot(symbol: string, row: any, ts?: number) {
  const sym = symbol.toUpperCase();
  snapshotBuffer.set(sym, { row, ts });
  
  // Maintain local state
  const existing = rowsMap.get(sym) || {};
  
  const updatedRow = { ...existing, ...row, _ts: ts || Date.now() };
  rowsMap.set(sym, updatedRow);

  // Track direction for changed fields
  Object.entries(row).forEach(([key, newVal]) => {
    if (typeof newVal === 'number') {
      const oldVal = existing[key];
      if (oldVal !== undefined && oldVal !== null && newVal !== oldVal) {
        propagateDirection(sym, key, newVal > oldVal ? "up" : "down");
      }
    }
  });

  // Dependency tracking
  if (updatedRow.Under_Symbol) {
    const underSym = updatedRow.Under_Symbol.toUpperCase();
    if (!underlyingToCWs.has(underSym)) underlyingToCWs.set(underSym, new Set());
    underlyingToCWs.get(underSym)!.add(sym);
  }

  // Instant update for priority listeners (charts, etc.)
  self.postMessage({ type: "INSTANT_SNAPSHOT", symbol: sym, row: updatedRow, ts });
}

function handlePatch(symbol: string, patch: any, ts?: number) {
  const sym = symbol.toUpperCase();
  const existingPatch = patchBuffer.get(sym)?.patch || {};
  patchBuffer.set(sym, { patch: { ...existingPatch, ...patch }, ts });
  
  // Update local state
  // BUGFIX: If the row doesn't exist yet (e.g. a volatility patch arrives before the full snapshot),
  // create a stub so the SAB is written and values aren't silently dropped.
  const row = rowsMap.get(sym) || { Symbol: sym };
  const updatedRow = { ...row, ...patch, _ts: ts || Date.now() };
  rowsMap.set(sym, updatedRow);

  // Track direction for changed fields
  Object.entries(patch).forEach(([key, newVal]) => {
    if (typeof newVal === 'number') {
      const oldVal = (row as any)[key];
      if (oldVal !== undefined && oldVal !== null && newVal !== oldVal) {
        propagateDirection(sym, key, newVal > oldVal ? "up" : "down");
      }
    }
  });

  // Special: If this is an underlying symbol, propagate its price to all dependent CWs
  // Requirement: Don't update Under_Prc/Under_Symbol values before 9:15 AM.
  if (isAfter915AM() && sym.length <= 3 && (patch.Traded !== undefined || patch.Ref !== undefined)) {
    const newUnderPrc = patch.Traded ?? patch.Ref;
    const dependents = underlyingToCWs.get(sym);
    if (dependents && newUnderPrc !== undefined) {
      dependents.forEach(cwSym => {
        const cwRow = rowsMap.get(cwSym);
        if (cwRow) {
          const oldUnderPrc = cwRow.Under_Prc;
          const updatedCw = { ...cwRow, Under_Prc: newUnderPrc };
          rowsMap.set(cwSym, updatedCw);
          
          if (newUnderPrc !== oldUnderPrc) {
            propagateDirection(cwSym, "Under_Prc", newUnderPrc > (oldUnderPrc || 0) ? "up" : "down");
          }
        }
      });
    }
  }

  // Instant update for priority listeners (charts, etc.)
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

  // Structural flush check (only if symbol count changes or initial flush)
  const isInitialFlush = lastStructuralFlush === 0;
  const shouldFlushStructural = isInitialFlush || rowsMap.size > lastFlushedRowsMap.size;

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
