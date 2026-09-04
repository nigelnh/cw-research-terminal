import { useSyncExternalStore } from "react";
import { QUOTE_COLUMNS, type QuoteColumnKey } from "./quote_columns";

const STORAGE_KEY = "cw-research:table-layout:v1";
interface TableLayout {
  columns: QuoteColumnKey[];
  rows: string[];
}
const defaults: TableLayout = {
  columns: QUOTE_COLUMNS.map((c) => c.key),
  rows: [],
};
const listeners = new Set<() => void>();
function readLayout(): TableLayout {
  try {
    const saved = JSON.parse(
      window.localStorage.getItem(STORAGE_KEY) || "null",
    );
    return {
      columns: columnOrder(Array.isArray(saved?.columns) ? saved.columns : []),
      rows: Array.isArray(saved?.rows)
        ? ([
            ...new Set(
              saved.rows.filter(
                (s: unknown): s is string => typeof s === "string",
              ),
            ),
          ] as string[])
        : [],
    };
  } catch {
    return defaults;
  }
}
let layout = readLayout();

export function completeOrder<T extends string>(
  available: readonly T[],
  preferred: readonly string[],
): T[] {
  return [
    ...new Set([
      ...preferred.filter((id): id is T => available.includes(id as T)),
      ...available,
    ]),
  ];
}

/** Keep session traded value beside trade price and migrate saved column ids. */
export function columnOrder(preferred: readonly string[]): QuoteColumnKey[] {
  const migrated = preferred.map((id) => (id === "tradedQuantity" ? "tradingValue" : id));
  const columns = completeOrder(defaults.columns, migrated);
  if (!migrated.includes("tradingValue")) {
    columns.splice(columns.indexOf("tradingValue"), 1);
    columns.splice(columns.indexOf("last") + 1, 0, "tradingValue");
  }
  if (!preferred.includes("issuer")) {
    columns.splice(columns.indexOf("issuer"), 1);
    columns.splice(columns.indexOf("dte") + 1, 0, "issuer");
  }
  return columns;
}
export function moveItem<T>(items: readonly T[], from: T, to: T): T[] {
  const start = items.indexOf(from),
    end = items.indexOf(to);
  if (start < 0 || end < 0 || start === end) return [...items];
  const next = [...items];
  next.splice(start, 1);
  next.splice(end, 0, from);
  return next;
}
export interface GroupedRow {
  symbol: string;
  kind: "stock" | "cw";
  underlying: string | null;
}
/** Move a whole parent group, or a child within its own group; never reparent. */
export function moveGroupedRows(
  rows: readonly GroupedRow[],
  from: string,
  to: string,
): string[] | null {
  const source = rows.find((r) => r.symbol === from),
    target = rows.find((r) => r.symbol === to);
  if (!source || !target || source === target) return null;
  if (source.kind === "cw") {
    if (
      target.kind !== "cw" ||
      !source.underlying ||
      source.underlying !== target.underlying
    )
      return null;
    const siblings = rows
      .filter((r) => r.kind === "cw" && r.underlying === source.underlying)
      .map((r) => r.symbol);
    const moved = moveItem(siblings, from, to);
    let i = 0;
    return rows.map((r) =>
      siblings.includes(r.symbol) ? moved[i++] : r.symbol,
    );
  }
  const targetParent =
    target.kind === "stock" ? target.symbol : target.underlying;
  const parents = rows.filter((r) => r.kind === "stock").map((r) => r.symbol);
  if (!targetParent || !parents.includes(targetParent) || targetParent === from)
    return null;
  const orderedParents = moveItem(parents, from, targetParent);
  const grouped = orderedParents.flatMap((symbol) => [
    symbol,
    ...rows
      .filter((r) => r.kind === "cw" && r.underlying === symbol)
      .map((r) => r.symbol),
  ]);
  return [
    ...grouped,
    ...rows.filter((r) => !grouped.includes(r.symbol)).map((r) => r.symbol),
  ];
}
function update(next: TableLayout) {
  layout = next;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {
    /* session order still works */
  }
  listeners.forEach((listener) => listener());
}
function onStorage(event: StorageEvent) {
  if (event.key !== STORAGE_KEY && event.key !== null) return;
  layout = readLayout();
  listeners.forEach((listener) => listener());
}
function subscribe(listener: () => void) {
  if (listeners.size === 0) window.addEventListener?.("storage", onStorage);
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0)
      window.removeEventListener?.("storage", onStorage);
  };
}
export function useWatchlistLayout() {
  const current = useSyncExternalStore(
    subscribe,
    () => layout,
    () => defaults,
  );
  return {
    ...current,
    moveColumn: (from: QuoteColumnKey, to: QuoteColumnKey) =>
      update({ ...layout, columns: moveItem(layout.columns, from, to) }),
    setRows: (rows: string[]) => update({ ...layout, rows }),
  };
}
