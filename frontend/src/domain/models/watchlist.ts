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
export const WATCHLIST_STORAGE_KEY_V2 = "cw-research-watchlist:v2";
export const CURRENT_WATCHLIST_SCHEMA_VERSION = 2;

/**
 * PRIMARY UI UNIVERSE
 * The exact 5 canonical symbols intended for the primary user-facing dashboard experience.
 */
export const PRIMARY_UI_UNIVERSE = [
  "HPG",
  "NVL",
  "VHM",
  "CTCB2601",
  "CVPB2615",
] as const;

export const DEFAULT_PRIMARY_WATCHLIST_ITEMS: WatchlistItem[] = [
  {
    symbol: "HPG",
    instrumentType: "STOCK",
    addedAt: 0,
  },
  {
    symbol: "NVL",
    instrumentType: "STOCK",
    addedAt: 0,
  },
  {
    symbol: "VHM",
    instrumentType: "STOCK",
    addedAt: 0,
  },
  {
    symbol: "CTCB2601",
    instrumentType: "CW",
    underlyingSymbol: "TCB",
    issuer: "KIS",
    strikePrice: 25000,
    exerciseRatio: 2,
    maturityDate: "2026-12-10",
    addedAt: 0,
  },
  {
    symbol: "CVPB2615",
    instrumentType: "CW",
    underlyingSymbol: "VPB",
    issuer: "ACBS",
    strikePrice: null,
    exerciseRatio: null,
    maturityDate: null,
    addedAt: 0,
  },
];

/**
 * Creates the canonical default research watchlist populated with the 5 primary UI universe symbols.
 */
export function createDefaultWatchlist(): ResearchWatchlist {
  return {
    id: "default_personal_watchlist",
    name: "My Personal Research Dashboard",
    items: [...DEFAULT_PRIMARY_WATCHLIST_ITEMS],
    createdAt: Date.now(),
    updatedAt: Date.now(),
    version: CURRENT_WATCHLIST_SCHEMA_VERSION,
  };
}

/**
 * LocalStorage Watchlist Persistence Utility with Versioned Migration
 */
export class WatchlistStorage {
  private storageKey: string;

  constructor(storageKey: string = WATCHLIST_STORAGE_KEY_V2) {
    this.storageKey = storageKey;
  }

  private sanitizeItems(rawItems: any[]): WatchlistItem[] {
    return rawItems
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
  }

  public loadWatchlist(): ResearchWatchlist {
    if (typeof window === "undefined" || !window.localStorage) {
      return createDefaultWatchlist();
    }

    try {
      // 1. Check current storage key (V2)
      const rawV2 = window.localStorage.getItem(this.storageKey);
      if (rawV2) {
        try {
          const parsed = JSON.parse(rawV2);
          if (parsed && typeof parsed === "object" && Array.isArray(parsed.items)) {
            if (parsed.version === CURRENT_WATCHLIST_SCHEMA_VERSION) {
              return {
                id: parsed.id || "default_personal_watchlist",
                name: parsed.name || "My Personal Research Dashboard",
                items: this.sanitizeItems(parsed.items),
                createdAt: typeof parsed.createdAt === "number" ? parsed.createdAt : Date.now(),
                updatedAt: typeof parsed.updatedAt === "number" ? parsed.updatedAt : Date.now(),
                version: CURRENT_WATCHLIST_SCHEMA_VERSION,
              };
            }
          }
        } catch {
          // If V2 is corrupt, fallback below
        }
      }

      // 2. Check for legacy V1 storage or pre-migration version (< 2)
      const rawV1 = window.localStorage.getItem(WATCHLIST_STORAGE_KEY_V1) || rawV2;
      if (rawV1) {
        try {
          const parsedV1 = JSON.parse(rawV1);
          if (parsedV1 && typeof parsedV1 === "object" && Array.isArray(parsedV1.items)) {
            // One-time migration: Replace legacy default seeded items with exact 5 primary universe symbols
            const migrated = createDefaultWatchlist();
            this.saveWatchlist(migrated);
            if (this.storageKey !== WATCHLIST_STORAGE_KEY_V1) {
              window.localStorage.removeItem(WATCHLIST_STORAGE_KEY_V1);
            }
            return migrated;
          }
        } catch {
          // Fall through to default
        }
      }

      // 3. Fresh default initialization
      const initial = createDefaultWatchlist();
      this.saveWatchlist(initial);
      return initial;
    } catch (e) {
      console.warn("[WatchlistStorage] Failed to parse stored watchlist, resetting to default:", e);
      const fallback = createDefaultWatchlist();
      try {
        this.saveWatchlist(fallback);
      } catch {
        // Ignore storage write errors in fallback
      }
      return fallback;
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
      if (this.storageKey !== WATCHLIST_STORAGE_KEY_V1) {
        window.localStorage.removeItem(WATCHLIST_STORAGE_KEY_V1);
      }
    } catch (e) {
      console.error("[WatchlistStorage] Failed to clear watchlist from localStorage:", e);
    }
  }
}

export const defaultWatchlistStorage = new WatchlistStorage();
