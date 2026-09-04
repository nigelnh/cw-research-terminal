/**
 * Grid Terminal — shared table primitives.
 *
 * Ports the "Direction C" prototype's exact sort / pin / colour logic:
 *   - 3-state header sort (asc -> desc -> none), nulls always sort last
 *   - row pinning: pinned rows float to the top of the ordered list
 *   - fmtChg(): signed percent -> { text, color } using the semantic market colours
 *   - priceColor(): HOSE ceiling / floor / reference bands for BID / ASK / TRD cells
 */
import React, { useCallback, useMemo, useState } from "react";
import { daysUntil } from "@/domain/quant_display";

/* --------------------------------------------------------------- formatters */

export const DASH = "—";

/** Grouped integer VND price. Missing -> "—" (never 0). */
export function fmtPrice(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return DASH;
  return v.toLocaleString("en-US", { maximumFractionDigits: 0 });
}

/** Grouped integer volume. */
export function fmtVol(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return DASH;
  return v.toLocaleString("en-US");
}

/** Session traded value (raw VND) as a compact T / B / M amount. */
export function fmtAmount(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v) || v <= 0) return DASH;
  const abs = Math.abs(v);
  if (abs >= 1e12) return `${(v / 1e12).toFixed(2)}T`;
  if (abs >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  return v.toLocaleString("en-US", { maximumFractionDigits: 0 });
}

/** Decimal fraction (0.214) -> "21.4%". */
export function fmtIV(v: number | null | undefined, dp = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return DASH;
  return `${(v * 100).toFixed(dp)}%`;
}

/** Exercise ratio number -> "n:1". */
export function fmtRatio(v: number | null | undefined): string {
  if (typeof v !== "number" || Number.isNaN(v) || v <= 0) return DASH;
  return `${v}:1`;
}

/**
 * Days-to-expiry as a BARE number (no "d" suffix, per the design spec). A backend-computed
 * DTE (analytics group) wins; otherwise count VN-calendar days to the last trading / maturity
 * date. Past dates -> "EXP".
 */
export function dteDisplay(
  lastTradingDate: string | null | undefined,
  maturityDate: string | null | undefined,
  backendDte?: number | null,
): string {
  if (typeof backendDte === "number") return backendDte >= 0 ? String(backendDte) : "EXP";
  const n = daysUntil(lastTradingDate || maturityDate);
  if (n === null) return DASH;
  return n >= 0 ? String(n) : "EXP";
}

/** Numeric DTE for sorting. */
export function dteNumber(
  lastTradingDate: string | null | undefined,
  maturityDate: string | null | undefined,
  backendDte?: number | null,
): number | null {
  if (typeof backendDte === "number") return backendDte;
  return daysUntil(lastTradingDate || maturityDate);
}

/* ------------------------------------------------------------------ colours */

export const MARKET_COLOR = {
  up: "var(--up)",
  down: "var(--down)",
  flat: "var(--flat)",
  null: "var(--price-null)",
  ceiling: "var(--price-ceiling)",
  floor: "var(--price-floor)",
} as const;

/** A displayed reference/limit keeps its band colour; unavailable values stay grey. */
export function priceBandColor(
  value: number | null | undefined,
  band: "reference" | "ceiling" | "floor",
): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return MARKET_COLOR.null;
  return MARKET_COLOR[band === "reference" ? "flat" : band];
}

/** Signed percent (already a percent number, e.g. -0.45) -> display text + colour. */
export function fmtChg(pct: number | null | undefined): { text: string; color: string } {
  if (pct === null || pct === undefined || Number.isNaN(pct)) {
    return { text: "—", color: "var(--t-46)" };
  }
  const color = pct > 0 ? MARKET_COLOR.up : pct < 0 ? MARKET_COLOR.down : MARKET_COLOR.flat;
  return { text: `${pct > 0 ? "+" : ""}${pct.toFixed(2)}%`, color };
}

export interface PriceColorRef {
  /** prior-session reference price (raw VND). */
  ref: number | null | undefined;
  /** Verified session ceiling; CW bands must never be inferred from a stock percentage. */
  ceiling?: number | null;
  /** backend floor price when known. */
  floor?: number | null;
}

/**
 * Colour for a price cell relative to the day's reference.
 *   null input            -> grey
 *   at / near ceiling      -> magenta
 *   at / near floor        -> blue
 *   above ref              -> up green
 *   below ref              -> down red
 *   equal                  -> flat yellow
 */
export function priceColor(
  v: number | null | undefined,
  ref: number | null | undefined | PriceColorRef,
): string {
  const r: PriceColorRef = typeof ref === "object" && ref !== null ? ref : { ref: ref as number | null };
  const refNum = r.ref;
  if (v === null || v === undefined || Number.isNaN(v) || refNum === null || refNum === undefined) {
    return MARKET_COLOR.null;
  }
  if (typeof r.ceiling === "number" && v >= r.ceiling) return MARKET_COLOR.ceiling;
  if (typeof r.floor === "number" && v <= r.floor) return MARKET_COLOR.floor;
  if (v > refNum) return MARKET_COLOR.up;
  if (v < refNum) return MARKET_COLOR.down;
  return MARKET_COLOR.flat;
}

/* --------------------------------------------------------------- sort + pin */

export type SortDir = "asc" | "desc";
export interface SortSpec {
  key: string;
  dir: SortDir;
}
export type SortFields<T> = Record<string, (row: T) => string | number | null | undefined>;

export interface SortPinApi<T> {
  ordered: T[];
  sort: SortSpec | null;
  toggleSort: (key: string) => void;
  clearOrder: () => void;
  sortMark: (key: string) => string;
  isPinned: (symbol: string) => boolean;
  togglePin: (symbol: string, e?: React.MouseEvent) => void;
  pinFill: (symbol: string) => string;
}

function isNullish(v: unknown): boolean {
  return v === null || v === undefined || (typeof v === "number" && Number.isNaN(v));
}

/**
 * @param rows      source rows (each must have a stable `symbol`)
 * @param fields    map of column key -> value getter (every sortable column)
 * @param keyOf     how to read the pin identity from a row (default: `row.symbol`)
 */
export function useSortPin<T>(
  rows: T[],
  fields: SortFields<T>,
  keyOf: (row: T) => string = (r) => (r as unknown as { symbol: string }).symbol,
): SortPinApi<T> {
  const [sort, setSort] = useState<SortSpec | null>(null);
  const [pinned, setPinned] = useState<string[]>([]);

  const toggleSort = useCallback((key: string) => {
    setSort((cur) => {
      if (!cur || cur.key !== key) return { key, dir: "asc" };
      if (cur.dir === "asc") return { key, dir: "desc" };
      return null;
    });
  }, []);

  const togglePin = useCallback((symbol: string, e?: React.MouseEvent) => {
    if (e) e.stopPropagation();
    setPinned((cur) => (cur.includes(symbol) ? cur.filter((s) => s !== symbol) : [...cur, symbol]));
  }, []);

  const ordered = useMemo(() => {
    let arr = rows.slice();
    if (sort) {
      const getter = fields[sort.key];
      if (getter) {
        arr.sort((a, b) => {
          const av = getter(a);
          const bv = getter(b);
          const an = isNullish(av);
          const bn = isNullish(bv);
          if (an && bn) return 0;
          if (an) return 1;
          if (bn) return -1;
          const cmp =
            typeof av === "string"
              ? av.localeCompare(bv as string)
              : (av as number) - (bv as number);
          return sort.dir === "asc" ? cmp : -cmp;
        });
      }
    }
    const pinnedSet = new Set(pinned);
    return arr
      .filter((r) => pinnedSet.has(keyOf(r)))
      .concat(arr.filter((r) => !pinnedSet.has(keyOf(r))));
  }, [rows, fields, sort, pinned, keyOf]);

  const sortMark = useCallback(
    (key: string) => (!sort || sort.key !== key ? "" : sort.dir === "asc" ? "▲" : "▼"),
    [sort],
  );
  const isPinned = useCallback((symbol: string) => pinned.includes(symbol), [pinned]);
  const pinFill = useCallback(
    (symbol: string) => (pinned.includes(symbol) ? "var(--accent)" : "transparent"),
    [pinned],
  );

  return { ordered, sort, toggleSort, sortMark, isPinned, togglePin, pinFill, clearOrder: () => { setSort(null); setPinned([]); } };
}

/* ------------------------------------------------------------------ pieces */

const HEAD_STYLE: React.CSSProperties = {
  cursor: "pointer",
  padding: "5px 8px",
  color: "var(--t-50)",
  fontWeight: 500,
  userSelect: "none",
  whiteSpace: "nowrap",
};

export function SortHeader({
  label,
  mark,
  onClick,
  align = "right",
  width,
  onKeyDown,
  style,
  ...props
}: {
  label: string;
  mark: string;
  onClick: () => void;
  align?: "left" | "right";
  width?: number | string;
} & Omit<React.ThHTMLAttributes<HTMLTableCellElement>, "align" | "width" | "onClick">) {
  return (
    <th
      {...props}
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(event) => {
        onKeyDown?.(event);
        if (!event.defaultPrevented && (event.key === "Enter" || event.key === " ")) {
          event.preventDefault(); onClick();
        }
      }}
      role="columnheader"
      aria-sort={mark === "▲" ? "ascending" : mark === "▼" ? "descending" : "none"}
      style={{ ...HEAD_STYLE, textAlign: align, width, ...style }}
    >
      <span className="watchlist-column-label" style={{ flexDirection: align === "right" ? "row-reverse" : "row" }}>
        <span>{label}</span>
        <svg aria-hidden="true" className="watchlist-sort-icon" viewBox="0 0 12 12" fill="currentColor" style={{ visibility: mark ? "visible" : "hidden" }}>
          <path d={mark === "▼" ? "M1 2h10L6 11Z" : "M1 10h10L6 1Z"} />
        </svg>
      </span>
    </th>
  );
}

/** Static (non-sortable) column header, styled to match SortHeader. */
export function PlainHeader({
  label,
  align = "right",
  width,
}: {
  label: string;
  align?: "left" | "right";
  width?: number | string;
}) {
  return (
    <th style={{ ...HEAD_STYLE, cursor: "default", textAlign: align, width }}>{label}</th>
  );
}

export function PinCell({
  symbol,
  fill,
  onToggle,
}: {
  symbol: string;
  fill: string;
  onToggle: (symbol: string, e?: React.MouseEvent) => void;
}) {
  return (
    <td style={{ padding: "0 4px", textAlign: "center", width: 20 }}>
      <button
        type="button"
        onClick={(e) => onToggle(symbol, e)}
        title={fill === "transparent" ? "Pin to top" : "Unpin"}
        aria-label={fill === "transparent" ? `Pin ${symbol} to top` : `Unpin ${symbol}`}
        style={{
          background: "none",
          border: "none",
          cursor: "pointer",
          padding: 2,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <svg width="8" height="8" viewBox="0 0 10 10">
          <circle cx="5" cy="5" r="4" fill={fill} stroke="var(--t-46)" strokeWidth="1" />
        </svg>
      </button>
    </td>
  );
}

/** Header <th> for the empty pin column. */
export function PinHeader() {
  return <th style={{ width: 20, padding: "5px 4px" }} aria-hidden />;
}

/* ---------------------------------------------------------- dismiss (hide row) */

/**
 * Client-side "remove from view" for a table. Non-destructive and session-only —
 * hidden symbols come back on reload. Watchlist membership / registry data are
 * untouched.
 */
export function useHiddenRows() {
  const [hidden, setHidden] = useState<Set<string>>(() => new Set());
  const hide = useCallback((symbol: string) => {
    setHidden((prev) => {
      const next = new Set(prev);
      next.add(symbol.toUpperCase());
      return next;
    });
  }, []);
  const reset = useCallback(() => setHidden(new Set()), []);
  const isHidden = useCallback((symbol: string) => hidden.has(symbol.toUpperCase()), [hidden]);
  return { hidden, count: hidden.size, hide, reset, isHidden };
}

/** Trailing "×" cell — hides the row from the current view. */
export function DismissCell({
  symbol,
  onDismiss,
}: {
  symbol: string;
  onDismiss: (symbol: string) => void;
}) {
  return (
    <td style={{ padding: "0 6px", textAlign: "center", width: 22 }}>
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          onDismiss(symbol);
        }}
        title={`Hide ${symbol} from this view`}
        aria-label={`Hide ${symbol} from this view`}
        className="focus-ring"
        style={{
          background: "none",
          border: "none",
          cursor: "pointer",
          padding: 2,
          lineHeight: 1,
          fontSize: 12,
          color: "var(--t-42)",
        }}
      >
        ×
      </button>
    </td>
  );
}

export function DismissHeader() {
  return <th style={{ width: 22, padding: "5px 4px" }} aria-hidden />;
}

/** "· N hidden — show all" affordance shown next to a section heading. */
export function HiddenNote({ count, onReset }: { count: number; onReset: () => void }) {
  if (count === 0) return null;
  return (
    <span style={{ fontSize: 10.5, color: "var(--t-46)" }}>
      · {count} hidden{" "}
      <button
        type="button"
        onClick={onReset}
        className="focus-ring"
        style={{
          background: "none",
          border: "none",
          cursor: "pointer",
          font: "inherit",
          color: "var(--accent)",
          textDecoration: "underline",
        }}
      >
        show all
      </button>
    </span>
  );
}
