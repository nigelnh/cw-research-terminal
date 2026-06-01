/**
 * Generic table view component
 * Renders any TableBase with flexible sizing and change flashing
 */

import React, { useLayoutEffect, useRef, useState } from "react";
import type { TableBase } from "./TableBase";
import { colors } from "@/design/tokens";

import { useEquityData } from "@/data/useEquityData";

interface TableViewProps<T extends Record<string, unknown>> {
  table: TableBase<T>;
  data: T[];
  hiddenColumns?: string[];
  lastChanges?: Map<string, "up" | "down">;
  emptyStateMessage?: string;
}

// Flash duration in ms
const FLASH_DURATION = 700;

// MEMOIZED CELL COMPONENT
const TableCell = React.memo(
  ({
    row,
    col,
    flash,
    isPinned,
    isDraggingCol,
    translateX,
    table,
    onDragStart,
    onDragEnd,
    idx,
    colIdx,
    isFlexLayout,
  }: {
    row: any;
    col: any;
    flash: "up" | "down" | undefined;
    isPinned: boolean;
    isDraggingCol: boolean;
    translateX: number;
    table: any;
    onDragStart: (e: React.DragEvent, index: number) => void;
    onDragEnd: () => void;
    idx: number;
    colIdx: number;
    isFlexLayout: boolean;
    containerWidth: number;
  }) => {
    const colKey = col.key;
    const { getRow } = useEquityData();

    const baseColor = col.getColor(row, getRow);

    // FLIP logic for columns
    const prevColIdxRef = useRef<number>(colIdx);
    const [isAnimatingX, setIsAnimatingX] = useState(false);
    const cellRef = useRef<HTMLDivElement>(null);

    useLayoutEffect(() => {
      if (prevColIdxRef.current !== colIdx && !isDraggingCol) {
        // Trigger a smooth transition when column index changes
        setIsAnimatingX(true);
        const timeoutId = setTimeout(() => setIsAnimatingX(false), 500);
        return () => clearTimeout(timeoutId);
      }
      prevColIdxRef.current = colIdx;
    }, [colIdx, isDraggingCol]);

    const getCellStyle = (): React.CSSProperties => {
      if (flash) {
        const customFlashColor = table.getFlashColor(row, colKey, flash, getRow);
        if (customFlashColor) {
          return {
            backgroundColor: customFlashColor,
            color: "#FFFFFF",
            transition: "background-color 0.05s ease, color 0.05s ease",
          };
        }

        if (flash === "up") {
          return {
            backgroundColor: colors.increase,
            color: "#FFFFFF",
            transition: "background-color 0.05s ease, color 0.05s ease",
          };
        } else if (flash === "down") {
          return {
            backgroundColor: colors.decrease,
            color: "#FFFFFF",
            transition: "background-color 0.05s ease, color 0.05s ease",
          };
        }
      }

      return {
        color: baseColor,
        backgroundColor: col.getBgColor(row, getRow),
        transition: "background-color 0.05s ease, color 0.05s ease",
      };
    };

    const config = table.config;
    const getColumnStyle = (): React.CSSProperties => {
      const baseWidth = 85;
      const rawWidth = col.widthPx || (col.flex ? col.flex * baseWidth : baseWidth);

      if (isFlexLayout) {
        // In flex layout, expand columns proportionally to cover all container space
        const growWeight = col.widthPx || col.flex || 1;
        const minWidthVal = col.widthPx ? Math.max(col.widthPx - 5, 50) : baseWidth;
        return {
          flexGrow: growWeight,
          flexShrink: 1,
          flexBasis: `${minWidthVal}px`,
          minWidth: `${minWidthVal}px`,
          boxSizing: "border-box",
        };
      } else {
        // Horizontal scrolling layout: strictly enforce column widths
        const calculatedWidth = rawWidth + 20;
        return {
          width: calculatedWidth,
          minWidth: calculatedWidth,
          maxWidth: calculatedWidth,
          flexShrink: 0,
          flexGrow: 0,
          boxSizing: "border-box",
        };
      }
    };

    return (
      <div
        ref={cellRef}
        title={colKey === "Symbol" ? "Double click to pin- Drag & Drop to sort row" : undefined}
        style={{
          ...getColumnStyle(),
          height: config.rowHeightPx,
          display: "flex",
          alignItems: "center",
          justifyContent:
            col.align === "right"
              ? "flex-end"
              : col.align === "center"
                ? "center"
                : "flex-start",
          padding: "0 8px",
          fontSize: config.fontSize,
          fontWeight: 500,
          whiteSpace: "nowrap",
          overflow: "hidden",
          textOverflow: "ellipsis",
          borderRight: `1px solid ${colors.borderSubtle}`,
          ...getCellStyle(),
          cursor: colKey === "Symbol" ? "grab" : "default",
          transition: (isDraggingCol || isAnimatingX)
            ? "transform 100ms cubic-bezier(0.4, 0, 0.2, 1), background-color 0.05s ease, color 0.05s ease"
            : "background-color 0.05s ease, color 0.05s ease",
          transform: `translateX(${translateX}px) translateZ(0)`,
          gap: 4,
        }}
        draggable={colKey === "Symbol"}
        onDragStart={(e) => colKey === "Symbol" && onDragStart(e, idx)}
        onDragEnd={onDragEnd}
      >
        {(() => {
          const displayVal = col.getDisplayValue(row);
          if (typeof displayVal === "string" && displayVal.startsWith("__LINK__")) {
            const href = displayVal.slice("__LINK__".length);
            return (
              <a
                href={href}
                target="_blank"
                rel="noopener noreferrer"
                onClick={(e) => e.stopPropagation()}
                style={{
                  color: "#0ECB81",
                  textDecoration: "none",
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 3,
                  fontSize: "inherit",
                  fontWeight: 600,
                  letterSpacing: "0.01em",
                }}
                onMouseEnter={(e) => {
                  (e.currentTarget as HTMLAnchorElement).style.textDecoration = "underline";
                }}
                onMouseLeave={(e) => {
                  (e.currentTarget as HTMLAnchorElement).style.textDecoration = "none";
                }}
              >
                View
              </a>
            );
          }
          return displayVal;
        })()}
        {colKey === "ticker" && row.div_d > 0 && (
          <span
            title={`Div Yield: ${(parseFloat(row.div_d) * 100).toFixed(2)}%`}
            style={{
              width: 7,
              height: 7,
              borderRadius: "50%",
              backgroundColor: "#9333EA", // Elegant glowing purple/indigo dot
              boxShadow: "0 0 8px #9333EA",
              display: "inline-block",
              marginLeft: 6,
              cursor: "help",
            }}
          />
        )}
        {isPinned && (
          <span
            className="material-symbols-outlined"
            style={{ fontSize: 14, color: colors.textSecondary, opacity: 0.8 }}
          >
            push_pin
          </span>
        )}
      </div>
    );
  },
  (prev, next) => {
    // 1. Core data for this specific cell
    const colKey = next.col.key;
    if (prev.row[colKey] !== next.row[colKey]) return false;

    // 2. Flash state
    if (prev.flash !== next.flash) return false;

    // 3. UI state
    if (prev.isPinned !== next.isPinned) return false;
    if (prev.isDraggingCol !== next.isDraggingCol) return false;
    if (prev.translateX !== next.translateX) return false;
    if (prev.idx !== next.idx) return false;
    if (prev.colIdx !== next.colIdx) return false;

    // 4. Container size & Layout mode
    if (prev.isFlexLayout !== next.isFlexLayout) return false;
    if (prev.containerWidth !== next.containerWidth) return false;

    // 5. Color dependencies
    // If the column uses dynamic coloring, check common price-related dependencies
    if (typeof next.col.color === "function") {
      // Always check Traded, Ref, Ceil, Floor as they affect almost all price colors
      if (prev.row.Traded !== next.row.Traded) return false;
      if (prev.row.Ref !== next.row.Ref) return false;
      if (prev.row.Ceil !== next.row.Ceil) return false;
      if (prev.row.Floor !== next.row.Floor) return false;

      // Explicit dependencies
      const deps = next.col.colorDependencies;
      if (deps && deps.length > 0) {
        for (const dep of deps) {
          if (prev.row[dep] !== next.row[dep]) return false;
        }
      }
    }

    // 6. Active flash synchronization
    return true;
  }
);

// MEMOIZED ROW COMPONENT
const TableRow = React.memo(
  ({
    row,
    idx,
    rowKey,
    columns,
    flashes,
    pinnedSymbols,
    draggedIdx,
    hoverIdx,
    draggedColKey,
    hoverColKey,
    measuredWidths,
    table,
    togglePin,
    onDragStart,
    onDragEnd,
    isFlexLayout,
    containerWidth,
  }: {
    row: any;
    idx: number;
    rowKey: string;
    columns: any[];
    flashes: Map<string, "up" | "down">;
    pinnedSymbols: Set<string | null>;
    draggedIdx: number | null;
    hoverIdx: number | null;
    draggedColKey: string | null;
    hoverColKey: string | null;
    measuredWidths: Map<string, number>;
    table: any;
    togglePin: (symbol: string) => void;
    onDragStart: (e: React.DragEvent, index: number) => void;
    onDragEnd: () => void;
    isFlexLayout: boolean;
    containerWidth: number;
  }) => {
    const [isHovered, setIsHovered] = useState(false);
    // Hydrate row with latest live numeric values from the in-memory row map.
    // lastUpdateTs dependency ensures re-hydration on every data tick (~50ms flush).
    const symbol = row.Symbol;
    const { getNumericValue, isSymbolDirty, lastUpdateTs } = useEquityData();
    const config = table.config;
    const prevHydratedRowRef = useRef<any>(null);

    const hydratedRow = React.useMemo(() => {
      // Non-equity tables (Holiday, Dividend, etc.) have no Symbol — skip hydration entirely.
      if (!symbol || !table.needsLiveHydration) return row;

      // If symbol is NOT dirty and we have a previous version, skip the hydration loop
      if (prevHydratedRowRef.current && !isSymbolDirty(symbol)) {
        return prevHydratedRowRef.current;
      }

      const next = { ...row };
      const fields = [
        "Ceil", "Floor", "Ref", "Ask1_Qty", "Ask1_Prc", "Traded", "Bid1_Prc", "Bid1_Qty",
        "Vol1", "Vol2", "Vol3", "Under_Prc", "Strike_Prc", "Ratio", "Traded_Qty", "Total_Vol",
        "FB", "FS", "FR", "FO", "Total_Val", "Avg_Prc", "Change", "ChangePercent"
      ];
      fields.forEach(field => {
        const val = getNumericValue(symbol, field);
        if (val !== null) next[field] = val;
      });

      prevHydratedRowRef.current = next;
      return next;
    }, [row, symbol, getNumericValue, isSymbolDirty, lastUpdateTs]);

    // FLIP logic for smooth row reordering
    const prevIdxRef = useRef<number>(idx);
    const [flipOffset, setFlipOffset] = useState(0);
    const [isAnimating, setIsAnimating] = useState(false);

    useLayoutEffect(() => {
      if (prevIdxRef.current !== idx && draggedIdx === null) {
        const delta = (prevIdxRef.current - idx) * config.rowHeightPx;

        // Step 1: Set the offset instantly (no animation)
        setFlipOffset(delta);
        setIsAnimating(false);

        // Step 2: Trigger the animation to 0 in the next frame
        const rafId = requestAnimationFrame(() => {
          setFlipOffset(0);
          setIsAnimating(true);
        });

        // Cleanup: remove animation class after transition is likely done
        const timeoutId = setTimeout(() => {
          setIsAnimating(false);
        }, 500);

        prevIdxRef.current = idx;
        return () => {
          cancelAnimationFrame(rafId);
          clearTimeout(timeoutId);
        };
      }
      prevIdxRef.current = idx;
    }, [idx, config.rowHeightPx, draggedIdx]);

    let translateY = 0;
    if (draggedIdx !== null && hoverIdx !== null) {
      if (idx === draggedIdx) {
        translateY = (hoverIdx - draggedIdx) * config.rowHeightPx;
      } else if (idx > draggedIdx && idx <= hoverIdx) {
        translateY = -config.rowHeightPx;
      } else if (idx < draggedIdx && idx >= hoverIdx) {
        translateY = config.rowHeightPx;
      }
    }

    const isDragging = draggedIdx === idx;

    const transitionString = isAnimating
      ? `transform 100ms cubic-bezier(0.4, 0, 0.2, 1), background-color 0.05s ease, opacity 0.2s ease`
      : draggedIdx !== null
        ? "transform 0.1s cubic-bezier(0.2, 0.8, 0.2, 1), background-color 0.05s ease, opacity 0.2s ease"
        : "background-color 0.05s ease";

    return (
      <div
        onMouseEnter={() => setIsHovered(true)}
        onMouseLeave={() => setIsHovered(false)}
        onDoubleClick={() => togglePin(rowKey)}
        style={{
          display: "flex",
          height: config.rowHeightPx,
          borderBottom: `1px solid ${colors.borderSubtle}`,
          backgroundColor: isHovered ? "rgba(255, 255, 255, 0.08)" : undefined,
          opacity: isDragging ? 0.3 : 1,
          transition: transitionString,
          transform: `translateY(${translateY + flipOffset}px) translateZ(0)`,
          zIndex: isDragging ? 100 : 1,
          position: "relative",
          pointerEvents: isDragging ? "none" : "auto",
          cursor: "pointer",
          width: isFlexLayout ? "100%" : "max-content",
          minWidth: "100%",
        }}
      >
        {columns.map((col, cIdx) => {
          const isPinned = col.key === "Symbol" && pinnedSymbols.has(rowKey);
          const cellKey = `${rowKey}:${col.key}`;
          const flash = flashes.get(cellKey);

          let translateX = 0;
          if (draggedColKey && hoverColKey) {
            const currentOrder = columns.map((c) => c.key);
            const dIdx = currentOrder.indexOf(draggedColKey);
            const hIdx = currentOrder.indexOf(hoverColKey);

            if (col.key === draggedColKey) {
              let distance = 0;
              if (dIdx < hIdx) {
                distance = columns
                  .slice(dIdx + 1, hIdx + 1)
                  .reduce((sum, c) => sum + (measuredWidths.get(c.key) || c.widthPx || 0), 0);
              } else if (dIdx > hIdx) {
                distance = -columns
                  .slice(hIdx, dIdx)
                  .reduce((sum, c) => sum + (measuredWidths.get(c.key) || c.widthPx || 0), 0);
              }
              translateX = distance;
            } else {
              const draggedWidth = measuredWidths.get(draggedColKey) || columns[dIdx].widthPx || 0;
              if (dIdx < hIdx && cIdx > dIdx && cIdx <= hIdx) {
                translateX = -draggedWidth;
              } else if (dIdx > hIdx && cIdx < dIdx && cIdx >= hIdx) {
                translateX = draggedWidth;
              }
            }
          }

          return (
            <TableCell
              key={col.key}
              row={hydratedRow}
              col={col}
              flash={flash}
              isPinned={isPinned}
              isDraggingCol={!!draggedColKey}
              translateX={translateX}
              table={table}
              onDragStart={onDragStart}
              onDragEnd={onDragEnd}
              idx={idx}
              colIdx={cIdx}
              isFlexLayout={isFlexLayout}
              containerWidth={containerWidth}
            />
          );
        })}
      </div>
    );
  }
);

// MEMOIZED HEADER CELL COMPONENT
const HeaderCell = React.memo(
  ({
    col,
    idx,
    sortConfig,
    handleSort,
    onColDragStart,
    onColDragEnd,
    draggedColKey,
    translateX,
    table,
    isFlexLayout,
  }: {
    col: any;
    idx: number;
    sortConfig: any;
    handleSort: (key: string) => void;
    onColDragStart: (e: React.DragEvent, key: string) => void;
    onColDragEnd: () => void;
    draggedColKey: string | null;
    translateX: number;
    table: any;
    isFlexLayout: boolean;
  }) => {
    const config = table.config;
    const isSorted = sortConfig?.key === col.key;
    const icon = sortConfig?.direction === "asc" ? "arrow_upward" : "arrow_downward";
    const isDraggingCol = draggedColKey === col.key;

    // FLIP logic for columns
    const prevIdxRef = useRef<number>(idx);
    const [isAnimating, setIsAnimating] = useState(false);

    useLayoutEffect(() => {
      if (prevIdxRef.current !== idx && !draggedColKey) {
        setIsAnimating(true);
        const timeoutId = setTimeout(() => setIsAnimating(false), 500);
        return () => clearTimeout(timeoutId);
      }
      prevIdxRef.current = idx;
    }, [idx, draggedColKey]);

    const getColumnStyle = (col: any): React.CSSProperties => {
      const baseWidth = 85;
      const rawWidth = col.widthPx || (col.flex ? col.flex * baseWidth : baseWidth);

      if (isFlexLayout) {
        // In flex layout, expand columns proportionally to cover all container space
        const growWeight = col.widthPx || col.flex || 1;
        const minWidthVal = col.widthPx ? Math.max(col.widthPx - 5, 50) : baseWidth;
        return {
          flexGrow: growWeight,
          flexShrink: 1,
          flexBasis: `${minWidthVal}px`,
          minWidth: `${minWidthVal}px`,
          boxSizing: "border-box",
        };
      } else {
        // Horizontal scrolling layout: strictly enforce column widths
        const calculatedWidth = rawWidth + 20;
        return {
          width: calculatedWidth,
          minWidth: calculatedWidth,
          maxWidth: calculatedWidth,
          flexShrink: 0,
          flexGrow: 0,
          boxSizing: "border-box",
        };
      }
    };

    return (
      <div
        onClick={() => handleSort(col.key)}
        draggable={true}
        onDragStart={(e) => onColDragStart(e, col.key)}
        onDragEnd={onColDragEnd}
        title="Drag & Drop to sort column"
        style={{
          ...getColumnStyle(col),
          height: config.headerHeightPx,
          display: "flex",
          alignItems: "center",
          cursor: col.sortable ? "pointer" : "default",
          userSelect: "none",
          justifyContent:
            col.align === "right"
              ? "flex-end"
              : col.align === "center"
                ? "center"
                : "flex-start",
          padding: "0 8px",
          fontSize: config.headerFontSize,
          fontWeight: 600,
          color: colors.textSecondary,
          whiteSpace: "nowrap",
          overflow: "hidden",
          textOverflow: "ellipsis",
          borderRight: `1px solid ${colors.borderSubtle}`,
          gap: 4,
          opacity: isDraggingCol ? 0.3 : 1,
          transition: (draggedColKey || isAnimating)
            ? "transform 400ms cubic-bezier(0.4, 0, 0.2, 1), opacity 0.2s ease, background-color 0.1s ease"
            : "background-color 0.1s ease",
          transform: `translateX(${translateX}px) translateZ(0)`,
          zIndex: isDraggingCol ? 100 : 1,
          position: "relative",
          backgroundColor: "#101010",
        }}
      >
        {!col.sortArrowOnRight && isSorted && (
          <span
            className="material-symbols-outlined"
            style={{ fontSize: 14, fontWeight: "bold" }}
          >
            {icon}
          </span>
        )}

        {col.header}

        {col.sortArrowOnRight && isSorted && (
          <span
            className="material-symbols-outlined"
            style={{ fontSize: 14, fontWeight: "bold" }}
          >
            {icon}
          </span>
        )}
      </div>
    );
  }
);

export function TableView<T extends Record<string, unknown>>({
  table,
  data,
  hiddenColumns = [],
  lastChanges,
  emptyStateMessage,
}: TableViewProps<T>) {
  const { getNumericValue } = useEquityData();

  const columns = table.getColumns().filter(c => !hiddenColumns.includes(c.key));
  const isFlexLayout = columns.length <= 20;
  const config = table.config;

  const totalColumnsWidth = React.useMemo(() => {
    const baseWidth = 85;
    return columns.reduce((sum, col) => {
      const rawWidth = col.widthPx || (col.flex ? col.flex * baseWidth : baseWidth);
      return sum + rawWidth + 20;
    }, 0);
  }, [columns]);

  const tableWidthStyle = isFlexLayout ? "100%" : `${totalColumnsWidth}px`;

  // Refs for precise coordinate detection
  const headerRef = useRef<HTMLDivElement>(null);
  const bodyRef = useRef<HTMLDivElement>(null);

  // Active flashes: cellKey -> { direction, expiry }
  const activeFlashesRef = useRef<Map<string, { dir: "up" | "down"; expire: number }>>(new Map());

  // Update active flashes during render for atomic sync with lastUpdateTs
  const currentFlashes = React.useMemo(() => {
    const now = Date.now();
    const map = activeFlashesRef.current;

    // 1. Add new changes
    if (lastChanges && lastChanges.size > 0) {
      lastChanges.forEach((direction, key) => {
        map.set(key, { dir: direction, expire: now + FLASH_DURATION });
      });
    }

    // 2. Cleanup expired and build current state
    const result = new Map<string, "up" | "down">();
    for (const [key, val] of map.entries()) {
      if (now > val.expire) {
        map.delete(key);
      } else {
        result.set(key, val.dir);
      }
    }
    return result;
  }, [lastChanges]); // Re-calculate when data ticks or changes arrive



  // Manual ordering for DnD
  const [manualOrder, setManualOrder] = useState<string[] | null>(null);
  const [draggedIdx, setDraggedIdx] = useState<number | null>(null);
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  // Column DnD
  const [manualColOrder, setManualColOrder] = useState<string[] | null>(null);
  const [draggedColKey, setDraggedColKey] = useState<string | null>(null);
  const [hoverColKey, setHoverColKey] = useState<string | null>(null);
  const [measuredWidths, setMeasuredWidths] = useState<Map<string, number>>(new Map());

  // Sort state
  const [sortConfig, setSortConfig] = useState<{
    key: string;
    direction: "asc" | "desc";
  } | null>(null);

  // Pinned symbols
  const [pinnedSymbols, setPinnedSymbols] = useState<Set<string | null>>(new Set());

  const togglePin = (symbol: string) => {
    setPinnedSymbols((prev) => {
      const next = new Set(prev);
      if (next.has(symbol)) {
        next.delete(symbol);
      } else {
        next.add(symbol);
      }
      return next;
    });
  };

  // Memoized columns based on manual order
  const sortedColumns = React.useMemo(() => {
    if (!manualColOrder) return columns;
    const orderMap = new Map(manualColOrder.map((key, i) => [key, i]));
    return [...columns].sort((a, b) => {
      const idxA = orderMap.get(a.key) ?? 999;
      const idxB = orderMap.get(b.key) ?? 999;
      return idxA - idxB;
    });
  }, [columns, manualColOrder]);

  const handleSort = (key: string) => {
    const col = columns.find((c) => c.key === key);
    if (col && !col.sortable) return;

    setManualOrder(null); // Clear manual order on sort
    setSortConfig((current) => {
      if (!current || current.key !== key) {
        return { key, direction: "asc" };
      }
      if (current.direction === "asc") {
        return { key, direction: "desc" };
      }
      return null; // 3rd click -> Reset
    });
  };

  // Sort data
  const sortedData = React.useMemo(() => {
    // Partition data into pinned and unpinned
    const pinnedRows = data.filter((r) => pinnedSymbols.has(table.getRowKey(r)));
    const unpinnedRows = data.filter((r) => !pinnedSymbols.has(table.getRowKey(r)));

    // 1. Sort pinned rows (always alphabetically by Symbol)
    pinnedRows.sort((a, b) => {
      const symA = String(table.getRowKey(a)).toLowerCase();
      const symB = String(table.getRowKey(b)).toLowerCase();
      return symA < symB ? -1 : 1;
    });

    // 2. Sort unpinned rows
    let sortedUnpinned = [...unpinnedRows];

    // Priority 1: User-initiated manual sorting (drag and drop)
    if (manualOrder && !sortConfig) {
      const orderMap = new Map(manualOrder.map((key, i) => [key, i]));
      sortedUnpinned.sort((a, b) => {
        const keyA = table.getRowKey(a);
        const keyB = table.getRowKey(b);
        const idxA = orderMap.get(keyA) ?? 999;
        const idxB = orderMap.get(keyB) ?? 999;
        return idxA - idxB;
      });
    } else {
      let activeSort = sortConfig;

      // Priority 2: Default sorting (Symbol A-Z)
      if (!activeSort && !manualOrder) {
        if (columns.some((c) => c.key === "Symbol")) {
          activeSort = { key: "Symbol", direction: "asc" };
        }
      }

      if (activeSort) {
        const { key, direction } = activeSort;
        const col = columns.find((c) => c.key === key);

        if (col) {
          sortedUnpinned.sort((a, b) => {
            const symA = table.getRowKey(a);
            const symB = table.getRowKey(b);

            // Prefer live numeric values from the in-memory row map for sorting
            const liveValA = getNumericValue(symA, key);
            const liveValB = getNumericValue(symB, key);

            const valA = liveValA !== null ? liveValA : col.getValue(a);
            const valB = liveValB !== null ? liveValB : col.getValue(b);

            if (valA === valB) return 0;

            const getRank = (v: unknown) => {
              if (v === undefined || v === null || v === "") return 0;
              // Project convention: -1 is displayed as NaN
              if (v === -1) return 1;
              const n = typeof v === "number" ? v : parseFloat(String(v));
              if (isNaN(n)) return 1; // Also strings are rank 1 (treated as NaN)
              return 2;
            };

            const rankA = getRank(valA);
            const rankB = getRank(valB);

            if (rankA !== rankB) {
              return direction === "asc" ? rankA - rankB : rankB - rankA;
            }

            // Same rank - perform type-specific comparison
            if (rankA === 2) {
              // Both are numbers
              const numA = typeof valA === "number" ? (valA as number) : parseFloat(String(valA));
              const numB = typeof valB === "number" ? (valB as number) : parseFloat(String(valB));
              return direction === "asc" ? numA - numB : numB - numA;
            }

            const strA = String(valA).toLowerCase();
            const strB = String(valB).toLowerCase();
            if (strA < strB) return direction === "asc" ? -1 : 1;
            if (strA > strB) return direction === "asc" ? 1 : -1;
            return 0;
          });
        }
      }
    }

    return [...pinnedRows, ...sortedUnpinned];
  }, [data, sortConfig, columns, manualOrder, pinnedSymbols, table]);

  const onDragStart = (e: React.DragEvent, index: number) => {
    setDraggedIdx(index);
    setHoverIdx(index);

    // Set ghost image to transparent if supported, or just let it be
    // e.dataTransfer.setDragImage(new Image(), 0, 0); 

    e.dataTransfer.setData("text/plain", index.toString());
    e.dataTransfer.effectAllowed = "move";
  };

  const onDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    if (draggedIdx === null || !bodyRef.current) return;

    const rect = bodyRef.current.getBoundingClientRect();
    const relativeY = e.clientY - rect.top;

    // Direct position-based detection for "exact" feeling
    const targetIdx = Math.floor(relativeY / config.rowHeightPx);
    const safeTargetIdx = Math.max(
      0,
      Math.min(targetIdx, sortedData.length - 1)
    );

    if (safeTargetIdx !== hoverIdx) {
      setHoverIdx(safeTargetIdx);
    }
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    if (draggedIdx === null || hoverIdx === null || draggedIdx === hoverIdx) {
      setDraggedIdx(null);
      setHoverIdx(null);
      return;
    }

    // Finalize the reorder
    const currentItems = sortedData.map((r) => table.getRowKey(r));
    const movingItemKey = currentItems[draggedIdx];

    const nextOrder = [...currentItems];
    nextOrder.splice(draggedIdx, 1);
    nextOrder.splice(hoverIdx, 0, movingItemKey);

    setManualOrder(nextOrder);
    setSortConfig(null);
    setDraggedIdx(null);
    setHoverIdx(null);
  };

  const onDragEnd = () => {
    setDraggedIdx(null);
    setHoverIdx(null);
  };

  // Column DnD Handlers
  const onColDragStart = (e: React.DragEvent, colKey: string) => {
    // Measure all columns before starting drag
    if (headerRef.current) {
      const widths = new Map<string, number>();
      const children = Array.from(headerRef.current.children) as HTMLElement[];
      sortedColumns.forEach((col, idx) => {
        if (children[idx]) {
          widths.set(col.key, children[idx].getBoundingClientRect().width);
        }
      });
      setMeasuredWidths(widths);
    }

    setDraggedColKey(colKey);
    setHoverColKey(colKey);
    e.dataTransfer.setData("text/col", colKey);
    e.dataTransfer.effectAllowed = "move";
  };

  const onColDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    if (!draggedColKey || !headerRef.current) return;

    const rect = headerRef.current.getBoundingClientRect();
    const relativeX = e.clientX - rect.left;

    // Calculate exact column under cursor by accumulating widths
    let accumulatedWidth = 0;
    let targetKey = sortedColumns[0].key;
    for (const col of sortedColumns) {
      const w = measuredWidths.get(col.key) || col.widthPx || 0;
      if (relativeX < accumulatedWidth + w) {
        targetKey = col.key;
        break;
      }
      accumulatedWidth += w;
      targetKey = col.key; // Fallback to last column
    }

    if (targetKey !== hoverColKey) {
      setHoverColKey(targetKey);
    }
  };

  const onColDrop = (e: React.DragEvent) => {
    e.preventDefault();
    if (!draggedColKey || !hoverColKey || draggedColKey === hoverColKey) {
      setDraggedColKey(null);
      setHoverColKey(null);
      return;
    }

    const currentOrder = sortedColumns.map(c => c.key);
    const oldIdx = currentOrder.indexOf(draggedColKey);
    const newIdx = currentOrder.indexOf(hoverColKey);

    const nextOrder = [...currentOrder];
    nextOrder.splice(oldIdx, 1);
    nextOrder.splice(newIdx, 0, draggedColKey);

    setManualColOrder(nextOrder);
    setDraggedColKey(null);
    setHoverColKey(null);
  };

  const onColDragEnd = () => {
    setDraggedColKey(null);
    setHoverColKey(null);
  };

  // custom hook for container sizing
  const [containerHeight, setContainerHeight] = useState(800);
  const [containerWidth, setContainerWidth] = useState(0);
  useLayoutEffect(() => {
    if (!containerRef.current) return;

    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) {
        setContainerHeight(entry.contentRect.height);
        setContainerWidth(entry.contentRect.width);
      }
    });

    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, []);

  // Scroll state
  const [scrollTop, setScrollTop] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);

  const onScroll = (e: React.UIEvent<HTMLDivElement>) => {
    setScrollTop(e.currentTarget.scrollTop);
  };

  // Virtualization calculations
  const rowHeight = config.rowHeightPx;
  const headerHeight = config.headerHeightPx;
  const bufferRows = 4;

  // Calculate visible range based on current scrollTop and measured height
  const startIndex = Math.max(0, Math.floor(scrollTop / rowHeight) - bufferRows);
  const visibleCount = Math.ceil(containerHeight / rowHeight);
  const endIndex = Math.min(sortedData.length, startIndex + visibleCount + bufferRows * 2);

  return (
    <div
      style={{
        width: "100%",
        backgroundColor: colors.background,
        border: `1px solid ${colors.border}`,
        borderRadius: 6,
        overflow: "hidden",
        maxHeight: "max(400px, 86vh)",
        display: "flex",
        flexDirection: "column",
      }}
    >
      <div
        ref={containerRef}
        onScroll={onScroll}
        style={{
          width: "100%",
          overflowX: "auto",
          overflowY: "auto",
          fontFamily: "'Inter', sans-serif",
          position: "relative",
          scrollbarGutter: "stable",
          flex: 1,
          minHeight: 0,
        }}
      >
        {/* 
          VIRTUALIZED HEADER 
          Uses sticky positioning at top: 0
      */}
        <div
          ref={headerRef}
          onDragOver={onColDragOver}
          onDrop={onColDrop}
          style={{
            display: "flex",
            height: headerHeight,
            backgroundColor: "#101010",
            borderBottom: `1px solid ${colors.borderSubtle}`,
            position: "sticky",
            top: 0,
            zIndex: 200,
            width: tableWidthStyle,
            minWidth: tableWidthStyle,
          }}
        >
          {sortedColumns.map((col, idx) => {
            let translateX = 0;
            if (draggedColKey && hoverColKey) {
              const currentOrder = sortedColumns.map((c) => c.key);
              const dIdx = currentOrder.indexOf(draggedColKey);
              const hIdx = currentOrder.indexOf(hoverColKey);

              if (col.key === draggedColKey) {
                let distance = 0;
                if (dIdx < hIdx) {
                  distance = sortedColumns
                    .slice(dIdx + 1, hIdx + 1)
                    .reduce((sum, c) => sum + (measuredWidths.get(c.key) || c.widthPx || 0), 0);
                } else if (dIdx > hIdx) {
                  distance = -sortedColumns
                    .slice(hIdx, dIdx)
                    .reduce((sum, c) => sum + (measuredWidths.get(c.key) || c.widthPx || 0), 0);
                }
                translateX = distance;
              } else {
                const draggedWidth = measuredWidths.get(draggedColKey) || sortedColumns[dIdx].widthPx || 0;
                if (dIdx < hIdx && idx > dIdx && idx <= hIdx) {
                  translateX = -draggedWidth;
                } else if (dIdx > hIdx && idx < dIdx && idx >= hIdx) {
                  translateX = draggedWidth;
                }
              }
            }

            return (
              <HeaderCell
                key={col.key}
                col={col}
                idx={idx}
                sortConfig={sortConfig}
                handleSort={handleSort}
                onColDragStart={onColDragStart}
                onColDragEnd={onColDragEnd}
                draggedColKey={draggedColKey}
                translateX={translateX}
                table={table}
                isFlexLayout={isFlexLayout}
              />
            );
          })}
        </div>

        {/* 
          VIRTUALIZED BODY 
          The total height container provides the correct scrollbar size
      */}
        <div
          ref={bodyRef}
          onDragOver={onDragOver}
          onDrop={onDrop}
          style={{
            position: "relative",
            height: sortedData.length === 0 && emptyStateMessage ? 120 : sortedData.length * rowHeight,
            boxSizing: "content-box",
            width: tableWidthStyle,
            minWidth: tableWidthStyle,
          }}
        >
          {sortedData.length === 0 && emptyStateMessage ? (
            <div
              style={{
                position: "absolute",
                top: 0,
                left: 0,
                width: "100%",
                height: "100%",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                color: colors.textMuted,
                fontSize: "12px",
                fontStyle: "italic",
                textAlign: "center",
                padding: "20px",
                boxSizing: "border-box",
              }}
            >
              {emptyStateMessage}
            </div>
          ) : (
            /* Render only visible range + buffers */
            sortedData.slice(startIndex, endIndex).map((row, relativeIdx) => {
              const idx = startIndex + relativeIdx;
              const rowKey = table.getRowKey(row, idx);

              return (
                <div
                  key={rowKey}
                  style={{
                    position: "absolute",
                    top: 0,
                    left: 0,
                    width: tableWidthStyle,
                    minWidth: tableWidthStyle,
                    height: rowHeight,
                    transform: `translateY(${idx * rowHeight}px) translateZ(0)`,
                    willChange: "transform",
                  }}
                >
                  <TableRow
                    row={row}
                    idx={idx}
                    rowKey={rowKey}
                    columns={sortedColumns}
                    flashes={currentFlashes}
                    pinnedSymbols={pinnedSymbols}
                    draggedIdx={draggedIdx}
                    hoverIdx={hoverIdx}
                    draggedColKey={draggedColKey}
                    hoverColKey={hoverColKey}
                    measuredWidths={measuredWidths}
                    table={table}
                    togglePin={togglePin}
                    onDragStart={onDragStart}
                    onDragEnd={onDragEnd}
                    isFlexLayout={isFlexLayout}
                    containerWidth={containerWidth}
                  />
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}
