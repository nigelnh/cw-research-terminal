/**
 * Watchlist Domain Model
 * Provider-independent representations for personal research watchlists.
 */

export type WatchlistInstrumentType = "CW" | "STOCK" | "INDEX";

export interface WatchlistItem {
  symbol: string; // Uppercase canonical symbol (e.g. "CFPT2401", "HPG", "VNINDEX")
  instrumentType: WatchlistInstrumentType;
  underlyingSymbol?: string | null; // For CW: stable identity hint (a CW's underlying never changes)
  addedAt: number; // Unix timestamp in ms
  notes?: string;
  /**
   * @deprecated Contract terms are NEVER authoritative here - they are resolved at render
   * time from the canonical backend registry (`useInstrumentSpecs`). Kept optional only so
   * older persisted payloads type-check during migration; the v3 migration nulls them and
   * nothing reads them for display.
   */
  issuer?: string | null;
  /** @deprecated see `issuer` */ strikePrice?: number | null;
  /** @deprecated see `issuer` */ exerciseRatio?: number | null;
  /** @deprecated see `issuer` */ maturityDate?: string | null;
  /** @deprecated see `issuer` */ lastTradingDate?: string | null;
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
export const WATCHLIST_STORAGE_KEY_V3 = "cw-research-watchlist:v3";
// v3: watchlist items store IDENTITY + PREFERENCE only. Frozen contract terms
// (issuer/strike/ratio/maturity/lastTradingDate) are stripped - they are resolved live
// from the canonical backend registry. Existing v1/v2 payloads migrate in place, keeping
// symbols, order, instrumentType, underlyingSymbol, addedAt and notes.
export const CURRENT_WATCHLIST_SCHEMA_VERSION = 3;

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
    addedAt: 0,
  },
  {
    symbol: "CVPB2615",
    instrumentType: "CW",
    underlyingSymbol: "VPB",
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

  constructor(storageKey: string = WATCHLIST_STORAGE_KEY_V3) {
    this.storageKey = storageKey;
  }

  /**
   * Normalise persisted items to the v3 shape: identity + preference only. Frozen contract
   * terms from older payloads are intentionally NOT carried forward - the app resolves them
   * live from the backend registry. Symbol order is preserved by the array order.
   */
  private sanitizeItems(rawItems: any[]): WatchlistItem[] {
    const seen = new Set<string>();
    return rawItems
      .filter((item: any) => item && typeof item.symbol === "string")
      .map((item: any): WatchlistItem => ({
        symbol: String(item.symbol).toUpperCase(),
        instrumentType: (item.instrumentType === "CW" || item.instrumentType === "COVERED_WARRANT")
          ? "CW"
          : (item.instrumentType === "INDEX" ? "INDEX" : "STOCK"),
        underlyingSymbol: item.underlyingSymbol ? String(item.underlyingSymbol).toUpperCase() : null,
        addedAt: typeof item.addedAt === "number" ? item.addedAt : Date.now(),
        notes: item.notes || undefined,
      }))
      .filter((it) => (seen.has(it.symbol) ? false : (seen.add(it.symbol), true)));
  }

  public loadWatchlist(): ResearchWatchlist {
    if (typeof window === "undefined" || !window.localStorage) {
      return createDefaultWatchlist();
    }

    try {
      // 1. Current schema (v3): identity-only items.
      const rawV3 = window.localStorage.getItem(this.storageKey);
      if (rawV3) {
        try {
          const parsed = JSON.parse(rawV3);
          if (parsed && typeof parsed === "object" && Array.isArray(parsed.items) &&
              parsed.version === CURRENT_WATCHLIST_SCHEMA_VERSION) {
            return {
              id: parsed.id || "default_personal_watchlist",
              name: parsed.name || "My Personal Research Dashboard",
              items: this.sanitizeItems(parsed.items),
              createdAt: typeof parsed.createdAt === "number" ? parsed.createdAt : Date.now(),
              updatedAt: typeof parsed.updatedAt === "number" ? parsed.updatedAt : Date.now(),
              version: CURRENT_WATCHLIST_SCHEMA_VERSION,
            };
          }
        } catch {
          // corrupt v3 -> fall through
        }
      }

      // 2. Migrate an older payload (v1/v2, or a v3 key still holding v2 data). Keep the
      //    user's symbols, ORDER, type, underlying hint, addedAt and notes; drop frozen
      //    contract terms.
      const rawOlder =
        window.localStorage.getItem(WATCHLIST_STORAGE_KEY_V2) ||
        window.localStorage.getItem(WATCHLIST_STORAGE_KEY_V1) ||
        rawV3;
      if (rawOlder) {
        try {
          const old = JSON.parse(rawOlder);
          if (old && typeof old === "object" && Array.isArray(old.items) && old.items.length > 0) {
            const migrated: ResearchWatchlist = {
              id: old.id || "default_personal_watchlist",
              name: old.name || "My Personal Research Dashboard",
              items: this.sanitizeItems(old.items),
              createdAt: typeof old.createdAt === "number" ? old.createdAt : Date.now(),
              updatedAt: Date.now(),
              version: CURRENT_WATCHLIST_SCHEMA_VERSION,
            };
            this.saveWatchlist(migrated);
            window.localStorage.removeItem(WATCHLIST_STORAGE_KEY_V1);
            window.localStorage.removeItem(WATCHLIST_STORAGE_KEY_V2);
            return migrated;
          }
        } catch {
          // fall through to default
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
