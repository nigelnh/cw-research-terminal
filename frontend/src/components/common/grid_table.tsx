/**
 * Grid Terminal — shared table primitives.
 *
 * Ports the "Direction C" prototype's exact sort / pin / colour logic:
 *   - 3-state header sort (asc -> desc -> none), nulls always sort last
 *   - row pinning: pinned rows float to the top of the ordered list
 *   - fmtChg(): signed percent -> { text, color } using the semantic market colours
 *   - priceColor(): HOSE ceiling / floor / reference bands for BID / ASK / TRD cells
 */
import { Pin, MoreHorizontal } from "lucide-react";
import { Popover } from "./ui";
import React, { useCallback, useMemo, useState } from "react";

/* --------------------------------------------------------------- formatters */

export const DASH = "—";

/** Grouped integer VND price. Missing -> "—" (never 0). */
export function fmtPrice(v: number | null | undefined, kind?: string): string {
  if (v === null || v === undefined || Number.isNaN(v)) return DASH;
  return v.toLocaleString("en-US", {
    minimumFractionDigits: kind === "INDEX" ? 2 : 0,
    maximumFractionDigits: kind === "INDEX" ? 2 : 0,
  });
}

/** Grouped integer volume. */
export function fmtVol(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return DASH;
  return v.toLocaleString("en-US");
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

/** Signed absolute change. Colour is supplementary, never the only direction signal. */
export function fmtSigned(v: number | null | undefined, kind?: string): string {
  if (v == null || !Number.isFinite(v)) return DASH;
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}${fmtPrice(Math.abs(v), kind)}`;
}

/** Calendar days to maturity in Vietnam; historical model DTE is shown separately. */
export function maturityDays(
  maturity: string | null | undefined,
  now = new Date(),
): number | null {
  if (!maturity || !/^\d{4}-\d{2}-\d{2}$/.test(maturity.slice(0, 10)))
    return null;
  const today = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Ho_Chi_Minh",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(now);
  const end = Date.parse(maturity.slice(0, 10) + "T00:00:00Z");
  const start = Date.parse(today + "T00:00:00Z");
  return Number.isFinite(end) ? Math.round((end - start) / 86400000) : null;
}

export function dteDisplay(
  _last: string | null | undefined,
  maturity: string | null | undefined,
  _modelDte?: number | null,
): string {
  const n = maturityDays(maturity);
  return n === null ? DASH : n < 0 ? "EXP" : String(n);
}
export function dteNumber(
  _last: string | null | undefined,
  maturity: string | null | undefined,
  _modelDte?: number | null,
): number | null {
  return maturityDays(maturity);
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

/** Signed percent (already a percent number, e.g. -0.45) -> display text + colour. */
export function fmtChg(pct: number | null | undefined): {
  text: string;
  color: string;
} {
  if (pct === null || pct === undefined || Number.isNaN(pct)) {
    return { text: "—", color: "var(--t-46)" };
  }
  const color =
    pct > 0 ? MARKET_COLOR.up : pct < 0 ? MARKET_COLOR.down : MARKET_COLOR.flat;
  return { text: `${pct > 0 ? "+" : ""}${pct.toFixed(2)}%`, color };
}

export interface PriceColorRef {
  /** prior-session reference price (raw VND). */
  ref: number | null | undefined;
  /** backend ceiling price when known — exact match wins over the ±7% heuristic. */
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
  const r: PriceColorRef =
    typeof ref === "object" && ref !== null
      ? ref
      : { ref: ref as number | null };
  const refNum = r.ref;
  if (
    v === null ||
    v === undefined ||
    Number.isNaN(v) ||
    refNum === null ||
    refNum === undefined
  ) {
    return MARKET_COLOR.null;
  }
  if (typeof r.ceiling === "number" && v >= r.ceiling)
    return MARKET_COLOR.ceiling;
  if (typeof r.floor === "number" && v <= r.floor) return MARKET_COLOR.floor;
  const ceiling = refNum * 1.07;
  const floor = refNum * 0.93;
  if (v >= ceiling - 0.5) return MARKET_COLOR.ceiling;
  if (v <= floor + 0.5) return MARKET_COLOR.floor;
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
export type SortFields<T> = Record<
  string,
  (row: T) => string | number | null | undefined
>;

export interface SortPinApi<T> {
  ordered: T[];
  sort: SortSpec | null;
  toggleSort: (key: string) => void;
  sortMark: (key: string) => string;
  isPinned: (symbol: string) => boolean;
  togglePin: (symbol: string, e?: React.MouseEvent) => void;
  pinFill: (symbol: string) => string;
}

function isNullish(v: unknown): boolean {
  return (
    v === null || v === undefined || (typeof v === "number" && Number.isNaN(v))
  );
}

/**
 * @param rows      source rows (each must have a stable `symbol`)
 * @param fields    map of column key -> value getter (every sortable column)
 * @param keyOf     how to read the pin identity from a row (default: `row.symbol`)
 */
export function useSortPin<T>(
  rows: T[],
  fields: SortFields<T>,
  keyOf: (row: T) => string = (r) =>
    (r as unknown as { symbol: string }).symbol,
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
    setPinned((cur) =>
      cur.includes(symbol) ? cur.filter((s) => s !== symbol) : [...cur, symbol],
    );
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
    (key: string) =>
      !sort || sort.key !== key ? "" : sort.dir === "asc" ? "▲" : "▼",
    [sort],
  );
  const isPinned = useCallback(
    (symbol: string) => pinned.includes(symbol),
    [pinned],
  );
  const pinFill = useCallback(
    (symbol: string) =>
      pinned.includes(symbol) ? "var(--accent)" : "transparent",
    [pinned],
  );

  return { ordered, sort, toggleSort, sortMark, isPinned, togglePin, pinFill };
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
}: {
  label: string;
  mark: string;
  onClick: () => void;
  align?: "left" | "right";
  width?: number | string;
}) {
  return (
    <th
      aria-sort={
        mark === "▲" ? "ascending" : mark === "▼" ? "descending" : "none"
      }
      style={{ textAlign: align, width }}
    >
      <button type="button" className="sort-button" onClick={onClick}>
        {label}
        <span className="sort-mark" aria-hidden="true">
          {mark || "↕"}
        </span>
      </button>
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
    <th style={{ ...HEAD_STYLE, cursor: "default", textAlign: align, width }}>
      {label}
    </th>
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
  const pinned = fill !== "transparent";
  return (
    <td className="row-control">
      <button
        type="button"
        className="icon-btn"
        title={pinned ? "Unpin" : "Pin within group"}
        aria-pressed={pinned}
        aria-label={pinned ? `Unpin ${symbol}` : `Pin ${symbol}`}
        onClick={(e) => onToggle(symbol, e)}
      >
        <Pin
          size={13}
          fill={pinned ? "var(--accent)" : "none"}
          color={pinned ? "var(--accent)" : "var(--t-46)"}
        />
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
  const isHidden = useCallback(
    (symbol: string) => hidden.has(symbol.toUpperCase()),
    [hidden],
  );
  const restore = useCallback(
    (symbol: string) =>
      setHidden((prev) => {
        const next = new Set(prev);
        next.delete(symbol.toUpperCase());
        return next;
      }),
    [],
  );
  return { hidden, count: hidden.size, hide, restore, reset, isHidden };
}

/** Trailing "×" cell — hides the row from the current view. */
export function DismissCell({
  symbol,
  onDismiss,
  onRemove,
}: {
  symbol: string;
  onDismiss: (symbol: string) => void;
  onRemove?: (symbol: string) => void;
}) {
  return (
    <td className="row-control">
      <Popover
        label={`Actions for ${symbol}`}
        width={225}
        className="icon-btn"
        icon={<MoreHorizontal size={16} />}
      >
        {(close) => (
          <div className="row-menu">
            <button
              className="btn"
              onClick={() => {
                onDismiss(symbol);
                close();
              }}
            >
              Hide from view
            </button>
            {onRemove && (
              <button
                className="btn"
                onClick={() => {
                  onRemove(symbol);
                  close();
                }}
              >
                Remove from watchlist
              </button>
            )}
          </div>
        )}
      </Popover>
    </td>
  );
}

export function DismissHeader() {
  return <th style={{ width: 22, padding: "5px 4px" }} aria-hidden />;
}

/** "· N hidden — show all" affordance shown next to a section heading. */
export function HiddenNote({
  count,
  onReset,
}: {
  count: number;
  onReset: () => void;
}) {
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
