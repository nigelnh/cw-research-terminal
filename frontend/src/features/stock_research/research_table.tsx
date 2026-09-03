import { useMemo, useRef, useState, type ReactNode } from "react";
import { DismissHeader, PinCell, PinHeader, SortHeader, useSortPin } from "@/components/common/grid_table";
import { completeOrder, moveItem } from "@/components/common/watchlist_layout";

export interface ResearchColumn<T> {
  key: string;
  label: string;
  align?: "left" | "right";
  value: (row: T) => string | number | null | undefined;
  render: (row: T) => ReactNode;
  color?: string | ((row: T) => string);
}

interface Layout { columns: string[]; rows: string[] }
const EMPTY_LAYOUT: Layout = { columns: [], rows: [] };
function readLayout(key: string): Layout {
  try {
    const saved = JSON.parse(window.localStorage.getItem(key) || "null");
    const ids = (values: unknown) => Array.isArray(values) ? [...new Set(values.filter((s): s is string => typeof s === "string"))] : [];
    return { columns: ids(saved?.columns), rows: ids(saved?.rows) };
  } catch { return EMPTY_LAYOUT; }
}

/** Independent table layouts; moving a research row never changes its instrument metadata. */
export function ResearchTable<T extends { symbol: string }>({
  id, label, rows, columns, selectedSymbol, matches, onSelect, actions, isLoading = false, isError = false,
}: {
  id: "warrants" | "stocks";
  label: string;
  rows: T[];
  columns: ResearchColumn<T>[];
  selectedSymbol: string | null;
  matches: Set<string>;
  onSelect: (symbol: string) => void;
  actions: (row: T) => ReactNode;
  isLoading?: boolean;
  isError?: boolean;
}) {
  const storageKey = `cw-research:registry-${id}-layout:v1`;
  const [layout, setLayout] = useState(() => readLayout(storageKey));
  const save = (next: Layout) => {
    setLayout(next);
    try { window.localStorage.setItem(storageKey, JSON.stringify(next)); } catch { /* Keep this session's layout. */ }
  };
  const orderedColumns = completeOrder(columns.map(c => c.key), layout.columns).map(key => columns.find(c => c.key === key)!);
  const fields = useMemo(() => Object.fromEntries(columns.map(c => [c.key, c.value])), [columns]);
  const manualRows = useMemo(() => {
    const bySymbol = new Map(rows.map(row => [row.symbol, row]));
    return completeOrder(rows.map(row => row.symbol), layout.rows).map(symbol => bySymbol.get(symbol)!);
  }, [rows, layout.rows]);
  const grid = useSortPin(manualRows, fields);
  const drag = useRef<{ type: "row" | "column"; key: string } | null>(null);
  const [dropTarget, setDropTarget] = useState<string | null>(null);
  const endDrag = () => { drag.current = null; setDropTarget(null); };
  const moveColumn = (from: string, to: string) => save({ ...layout, columns: moveItem(orderedColumns.map(c => c.key), from, to) });
  const moveRow = (from: string, to: string) => {
    if (from === to) return;
    const visible = grid.ordered.map(row => row.symbol);
    if (!visible.includes(from) || !visible.includes(to)) return;
    save({ ...layout, rows: [...moveItem(visible, from, to), ...layout.rows.filter(symbol => !visible.includes(symbol))] });
    grid.clearOrder();
  };
  const dragProps = (type: "row" | "column", key: string) => ({
    draggable: true,
    onDragStart: (event: React.DragEvent) => {
      if ((event.target as HTMLElement).closest("button")) { event.preventDefault(); return; }
      drag.current = { type, key };
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", key);
    },
    onDragOver: (event: React.DragEvent) => {
      if (drag.current?.type !== type) return;
      event.preventDefault(); event.dataTransfer.dropEffect = "move"; setDropTarget(`${type}:${key}`);
    },
    onDrop: (event: React.DragEvent) => {
      if (drag.current?.type !== type) return;
      event.preventDefault();
      if (type === "column") moveColumn(drag.current.key, key);
      else moveRow(drag.current.key, key);
      endDrag();
    },
    onDragEnd: endDrag,
  });

  return <div className="registry-table-scroll">
    <table aria-label={label} className="mono grid-lined registry-table" style={{ width: "100%", borderCollapse: "collapse", fontSize: 11.5 }}>
      <thead><tr>
        <PinHeader />
        {orderedColumns.map((column, index) => <SortHeader key={column.key} label={column.label} align={column.align}
          data-column={column.key} mark={grid.sortMark(column.key)} onClick={() => { if (!drag.current) grid.toggleSort(column.key); }}
          title="Click to sort · Drag to reorder · Alt + ←/→ to move"
          className={dropTarget === `column:${column.key}` ? "is-drop-target" : undefined}
          style={{ cursor: "grab", width: column.key === "lastTradingDate" ? "1%" : undefined }}
          {...dragProps("column", column.key)}
          onKeyDown={(event) => {
            if (!event.altKey || !["ArrowLeft", "ArrowRight"].includes(event.key)) return;
            event.preventDefault();
            const to = orderedColumns[index + (event.key === "ArrowLeft" ? -1 : 1)];
            if (to) moveColumn(column.key, to.key);
          }} />)}
        <th style={{ width: 20 }} aria-hidden />
        <DismissHeader />
      </tr></thead>
      <tbody>
        {isLoading || isError || !grid.ordered.length ? <tr><td colSpan={columns.length + 3}
          style={{ padding: "40px 8px", textAlign: "center", color: isError ? "var(--down)" : "var(--t-46)" }}>
          {isLoading ? "Loading research registry…" : isError ? "Could not load the research registry. Retry shortly." : "No instruments match."}
        </td></tr> : grid.ordered.map((row, index) => <tr key={row.symbol} data-symbol={row.symbol} tabIndex={0}
          className={`registry-row${matches.has(row.symbol) ? " is-search-match" : ""}${selectedSymbol === row.symbol ? " is-selected" : ""}${dropTarget === `row:${row.symbol}` ? " is-drop-target" : ""}`}
          title="Drag to reorder · Alt + ↑/↓ to move"
          {...dragProps("row", row.symbol)}
          onClick={() => { if (!drag.current) onSelect(row.symbol); }}
          onKeyDown={(event) => {
            if (event.target !== event.currentTarget) return;
            if (event.key === "Enter") { event.preventDefault(); onSelect(row.symbol); }
            if (event.altKey && ["ArrowUp", "ArrowDown"].includes(event.key)) {
              event.preventDefault();
              const to = grid.ordered[index + (event.key === "ArrowUp" ? -1 : 1)];
              if (to) moveRow(row.symbol, to.symbol);
            }
          }}
          style={{ height: 27, cursor: "pointer", background: selectedSymbol === row.symbol || matches.has(row.symbol) ? "var(--panel-3)" : id === "warrants" ? "var(--panel-2)" : "transparent" }}>
          <PinCell symbol={row.symbol} fill={grid.pinFill(row.symbol)} onToggle={grid.togglePin} />
          {orderedColumns.map(column => <td key={column.key} style={{ padding: "0 8px", textAlign: column.align ?? "right", color: typeof column.color === "function" ? column.color(row) : column.color ?? "var(--t-60)" }}>
            {column.render(row)}
          </td>)}
          {actions(row)}
        </tr>)}
      </tbody>
    </table>
  </div>;
}
