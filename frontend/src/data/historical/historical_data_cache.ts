/**
 * CW Research Platform — Temporary Versioned LocalStorage Historical Cache
 * Schema Version: 1
 * Namespace: cw_research:historical:v1:{SYMBOL}:{DATASET}
 *
 * NOTE: This is a TEMPORARY_PROJECT_DESIGN client-side cache to minimize
 * FiinQuant requests and respect rate limits. A persistent backend database
 * will complement or replace this in a future iteration.
 */

export const HISTORICAL_CACHE_PREFIX = "cw_research:historical:v1";
export const MAX_CACHED_SYMBOLS = 20;

export type HistoricalDataset = "intraday_1d" | "intraday_5d" | "daily_1y";

export interface HistoricalBarRow {
  date: string;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  volume: number | null;
  adjusted?: boolean;
}

export interface HistoricalCacheRecord {
  schema_version: 1;
  symbol: string;
  dataset: HistoricalDataset;
  interval: string;
  adjusted: boolean;
  fetched_at: number;
  data_through: string;
  rows: HistoricalBarRow[];
}

/**
 * Returns canonical localStorage key for a symbol and dataset.
 */
export function getHistoricalCacheKey(symbol: string, dataset: HistoricalDataset): string {
  return `${HISTORICAL_CACHE_PREFIX}:${symbol.trim().toUpperCase()}:${dataset}`;
}

/**
 * Gets Vietnam (UTC+7) calendar date string YYYY-MM-DD for a timestamp.
 */
export function getVietnamDateString(timestamp: number): string {
  const date = new Date(timestamp);
  // Format in Asia/Ho_Chi_Minh timezone
  try {
    const formatter = new Intl.DateTimeFormat("en-CA", {
      timeZone: "Asia/Ho_Chi_Minh",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    });
    return formatter.format(date); // Outputs YYYY-MM-DD
  } catch {
    return date.toISOString().split("T")[0];
  }
}

export class HistoricalDataCache {
  /**
   * Reads a cached historical record from localStorage.
   */
  static get(symbol: string, dataset: HistoricalDataset): HistoricalCacheRecord | null {
    if (typeof window === "undefined" || !window.localStorage) return null;
    try {
      const key = getHistoricalCacheKey(symbol, dataset);
      const raw = window.localStorage.getItem(key);
      if (!raw) return null;

      const record: HistoricalCacheRecord = JSON.parse(raw);
      if (
        record &&
        record.schema_version === 1 &&
        record.symbol === symbol.trim().toUpperCase() &&
        record.dataset === dataset &&
        Array.isArray(record.rows)
      ) {
        return record;
      }
    } catch {
      // Ignore parse errors
    }
    return null;
  }

  /**
   * Checks if a cached record is fresh according to dataset validity policy.
   */
  static isFresh(
    record: HistoricalCacheRecord,
    isTradingActive: boolean = false,
    now: number = Date.now()
  ): boolean {
    if (!record || !record.rows || record.rows.length === 0) return false;

    // Daily 1Y dataset: reusable throughout the same Vietnam calendar day
    if (record.dataset === "daily_1y") {
      const fetchDateVN = getVietnamDateString(record.fetched_at);
      const nowDateVN = getVietnamDateString(now);
      return fetchDateVN === nowDateVN;
    }

    // Intraday 1D dataset (5m bars)
    if (record.dataset === "intraday_1d") {
      if (!isTradingActive) {
        // Outside trading session (lunch break or market closed): reuse same-day data
        const fetchDateVN = getVietnamDateString(record.fetched_at);
        const nowDateVN = getVietnamDateString(now);
        return fetchDateVN === nowDateVN;
      }
      // During active trading session: fresh for 5 minutes (300s)
      return now - record.fetched_at < 300 * 1000;
    }

    // Intraday 5D dataset (30m bars)
    if (record.dataset === "intraday_5d") {
      if (!isTradingActive) {
        const fetchDateVN = getVietnamDateString(record.fetched_at);
        const nowDateVN = getVietnamDateString(now);
        return fetchDateVN === nowDateVN;
      }
      // During active trading session: fresh for 10 minutes (600s)
      return now - record.fetched_at < 600 * 1000;
    }

    return false;
  }

  /**
   * Writes a historical record to localStorage and performs LRU eviction if over symbol limit.
   */
  static set(
    symbol: string,
    dataset: HistoricalDataset,
    rows: HistoricalBarRow[],
    interval: string = "1d",
    adjusted: boolean = true
  ): void {
    if (typeof window === "undefined" || !window.localStorage) return;

    try {
      const sym = symbol.trim().toUpperCase();
      const key = getHistoricalCacheKey(sym, dataset);
      const now = Date.now();
      const lastRow = rows.length > 0 ? rows[rows.length - 1] : null;

      const record: HistoricalCacheRecord = {
        schema_version: 1,
        symbol: sym,
        dataset,
        interval,
        adjusted,
        fetched_at: now,
        data_through: lastRow ? lastRow.date : "",
        rows,
      };

      window.localStorage.setItem(key, JSON.stringify(record));
      HistoricalDataCache.evictIfNeeded(sym);
    } catch {
      // Ignore quota errors
    }
  }

  /**
   * Removes a specific cached dataset for a symbol.
   */
  static remove(symbol: string, dataset: HistoricalDataset): void {
    if (typeof window === "undefined" || !window.localStorage) return;
    try {
      const key = getHistoricalCacheKey(symbol, dataset);
      window.localStorage.removeItem(key);
    } catch {
      // Ignore
    }
  }

  /**
   * Evicts oldest historical cache entries when symbol count exceeds MAX_CACHED_SYMBOLS.
   * STRICT GUARANTEE: Never touches keys outside `cw_research:historical:*`.
   */
  static evictIfNeeded(activeSymbol?: string): void {
    if (typeof window === "undefined" || !window.localStorage) return;

    try {
      const historicalKeys: { key: string; symbol: string; fetched_at: number }[] = [];
      const symbolsSet = new Set<string>();

      for (let i = 0; i < window.localStorage.length; i++) {
        const key = window.localStorage.key(i);
        if (key && key.startsWith(`${HISTORICAL_CACHE_PREFIX}:`)) {
          try {
            const raw = window.localStorage.getItem(key);
            if (raw) {
              const parsed = JSON.parse(raw);
              if (parsed && typeof parsed.fetched_at === "number") {
                const sym = parsed.symbol || key.split(":")[3] || "";
                symbolsSet.add(sym);
                historicalKeys.push({ key, symbol: sym, fetched_at: parsed.fetched_at });
              }
            }
          } catch {
            historicalKeys.push({ key, symbol: "", fetched_at: 0 });
          }
        }
      }

      if (symbolsSet.size > MAX_CACHED_SYMBOLS) {
        // Sort oldest fetched first
        historicalKeys.sort((a, b) => a.fetched_at - b.fetched_at);
        const activeSym = activeSymbol ? activeSymbol.trim().toUpperCase() : "";

        // Collect oldest symbols to evict
        const symbolsToEvict = new Set<string>();
        for (const item of historicalKeys) {
          if (item.symbol && item.symbol !== activeSym) {
            symbolsToEvict.add(item.symbol);
            if (symbolsSet.size - symbolsToEvict.size <= MAX_CACHED_SYMBOLS) {
              break;
            }
          }
        }

        // Delete all dataset keys for evicted symbols
        for (const item of historicalKeys) {
          if (symbolsToEvict.has(item.symbol)) {
            window.localStorage.removeItem(item.key);
          }
        }
      }
    } catch {
      // Ignore
    }
  }
}
