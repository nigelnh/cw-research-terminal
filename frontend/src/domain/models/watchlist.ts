/**
 * Watchlist Domain Model
 * Provider-independent representations for personal research watchlists.
 */

export type WatchlistInstrumentType = "CW" | "STOCK" | "INDEX";

export interface WatchlistItem {
  symbol: string; // Uppercase canonical symbol (e.g. "CFPT2401", "HPG", "VNINDEX")
  instrumentType: WatchlistInstrumentType;
  underlyingSymbol?: string | null; // For CW: e.g. "FPT"
  issuer?: string | null;
  strikePrice?: number | null;
  exerciseRatio?: number | null;
  maturityDate?: string | null;
  lastTradingDate?: string | null;
  addedAt: number; // Unix timestamp in ms
  notes?: string;
}

export interface ResearchWatchlist {
  id: string;
  name: string;
  items: WatchlistItem[];
  createdAt: number;
  updatedAt: number;
  version: number; // Schema version for persistence migrations
}

export const WATCHLIST_STORAGE_KEY_V1 = "cw-research-watchlist:v1";
export const CURRENT_WATCHLIST_SCHEMA_VERSION = 1;

/**
 * Creates an empty default research watchlist.
 */
export function createDefaultWatchlist(): ResearchWatchlist {
  return {
    id: "default_personal_watchlist",
    name: "My Personal Research Dashboard",
    items: [],
    createdAt: Date.now(),
    updatedAt: Date.now(),
    version: CURRENT_WATCHLIST_SCHEMA_VERSION,
  };
}

/**
 * LocalStorage Watchlist Persistence Utility
 */
export class WatchlistStorage {
  private storageKey: string;

  constructor(storageKey: string = WATCHLIST_STORAGE_KEY_V1) {
    this.storageKey = storageKey;
  }

  public loadWatchlist(): ResearchWatchlist {
    if (typeof window === "undefined" || !window.localStorage) {
      return createDefaultWatchlist();
    }

    try {
      const raw = window.localStorage.getItem(this.storageKey);
      if (!raw) {
        const initial = createDefaultWatchlist();
        this.saveWatchlist(initial);
        return initial;
      }

      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object" || !Array.isArray(parsed.items)) {
        return createDefaultWatchlist();
      }

      // Sanitize items
      const sanitizedItems: WatchlistItem[] = parsed.items
        .filter((item: any) => item && typeof item.symbol === "string")
        .map((item: any) => ({
          symbol: String(item.symbol).toUpperCase(),
          instrumentType: (item.instrumentType === "CW" || item.instrumentType === "COVERED_WARRANT") 
            ? "CW" 
            : (item.instrumentType === "INDEX" ? "INDEX" : "STOCK"),
          underlyingSymbol: item.underlyingSymbol ? String(item.underlyingSymbol).toUpperCase() : null,
          issuer: item.issuer || null,
          strikePrice: typeof item.strikePrice === "number" ? item.strikePrice : null,
          exerciseRatio: typeof item.exerciseRatio === "number" ? item.exerciseRatio : null,
          maturityDate: item.maturityDate || null,
          lastTradingDate: item.lastTradingDate || null,
          addedAt: typeof item.addedAt === "number" ? item.addedAt : Date.now(),
          notes: item.notes || undefined,
        }));

      return {
        id: parsed.id || "default_personal_watchlist",
        name: parsed.name || "My Personal Research Dashboard",
        items: sanitizedItems,
        createdAt: typeof parsed.createdAt === "number" ? parsed.createdAt : Date.now(),
        updatedAt: typeof parsed.updatedAt === "number" ? parsed.updatedAt : Date.now(),
        version: CURRENT_WATCHLIST_SCHEMA_VERSION,
      };
    } catch (e) {
      console.warn("[WatchlistStorage] Failed to parse stored watchlist, resetting to default:", e);
      return createDefaultWatchlist();
    }
  }

  public saveWatchlist(watchlist: ResearchWatchlist): void {
    if (typeof window === "undefined" || !window.localStorage) return;

    try {
      const payload: ResearchWatchlist = {
        ...watchlist,
        updatedAt: Date.now(),
        version: CURRENT_WATCHLIST_SCHEMA_VERSION,
      };
      window.localStorage.setItem(this.storageKey, JSON.stringify(payload));
    } catch (e) {
      console.error("[WatchlistStorage] Failed to save watchlist to localStorage:", e);
    }
  }

  public clear(): void {
    if (typeof window === "undefined" || !window.localStorage) return;
    try {
      window.localStorage.removeItem(this.storageKey);
    } catch (e) {
      console.error("[WatchlistStorage] Failed to clear watchlist from localStorage:", e);
    }
  }
}

export const defaultWatchlistStorage = new WatchlistStorage();
