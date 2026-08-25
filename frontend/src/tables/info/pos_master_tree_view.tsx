/**
 * PosMasterTreeView — Hierarchical tree-table for Position Master
 *
 * Groups CW rows (MM account, und_ticker !== ticker) as children under their
 * underlying stock rows (Hedge account, und_ticker === ticker) as parents.
 * If no hedging row exists for an underlying, a synthetic parent is created
 * from aggregated child data and live WebSocket equity prices.
 */

import React, { useState, useRef, useLayoutEffect, useMemo } from "react";
import { posMasterTable } from "./pos_master_table";
import type { PosColumnGroup } from "./pos_master_table";
import { colors, tableConfig } from "@/design/tokens";
import { useEquityData } from "@/data/use_equity_data";

// Flash duration ms
const FLASH_DURATION = 700;

// Per-underlying accent colors (cycled)
const ACCENT_PALETTE = [
  "#0ECB81",
  "#3B82F6",
  "#F59E0B",
  "#A855F7",
  "#EC4899",
  "#14B8A6",
  "#F97316",
  "#6366F1",
  "#10B981",
  "#EF4444",
];

interface PosMasterTreeViewProps {
  data: any[];
  hiddenColumns?: string[];
  lastChanges?: Map<string, "up" | "down">;
  posColumnGroup: PosColumnGroup;
  userEmail?: string;
}

type FlatRow = {
  row: any;
  isParent: boolean;
  undTicker: string;
  accentColor: string;
};

// ─── Header cell ──────────────────────────────────────────────────────────────
const HeaderCell = React.memo(
  ({
    col,
    width,
    isFlexLayout,
  }: {
    col: any;
    width: number;
    isFlexLayout: boolean;
  }) => {
    const config = posMasterTable.config;

    const getColumnStyle = (): React.CSSProperties => {
      const rawWidth = width;
      if (isFlexLayout) {
        const growWeight = rawWidth;
        const minWidthVal = Math.max(rawWidth - 5, 50);
        return {
          flexGrow: growWeight,
          flexShrink: 1,
          flexBasis: `${minWidthVal}px`,
          minWidth: `${minWidthVal}px`,
          boxSizing: "border-box",
        };
      } else {
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
        style={{
          ...getColumnStyle(),
          height: config.headerHeightPx,
          display: "flex",
          alignItems: "center",
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
          backgroundColor: "#101010",
          userSelect: "none",
        }}
      >
        {col.header}
      </div>
    );
  }
);

// ─── Tree data cell ───────────────────────────────────────────────────────────
const TreeCell = React.memo(
  ({
    col,
    row,
    width,
    isParent,
    isFirstCol,
    isCollapsed,
    // accentColor is intentionally not destructured here;
    // it is consumed at the row-container level (borderLeft) outside this cell.
    flash,
    isFlexLayout,
  }: {
    col: any;
    row: any;
    width: number;
    isParent: boolean;
    isFirstCol: boolean;
    isCollapsed: boolean;
    accentColor: string; // kept for API compatibility; row border uses it at the container level
    flash: "up" | "down" | undefined;
    isFlexLayout: boolean;
  }) => {
    const { getRow } = useEquityData();
    const config = posMasterTable.config;

    const baseColor = col.getColor(row, getRow);
    const cellBgColor = col.getBgColor(row, getRow);

    const getColumnStyle = (): React.CSSProperties => {
      const rawWidth = width;
      if (isFlexLayout) {
        const growWeight = rawWidth;
        const minWidthVal = Math.max(rawWidth - 5, 50);
        return {
          flexGrow: growWeight,
          flexShrink: 1,
          flexBasis: `${minWidthVal}px`,
          minWidth: `${minWidthVal}px`,
          boxSizing: "border-box",
        };
      } else {
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

    const displayVal = col.getDisplayValue(row);
    const rawVal = col.getValue(row);
    const isValNullOrNA = displayVal === "N/A" || displayVal === "" || rawVal === null || rawVal === undefined;

    const getCellStyle = (): React.CSSProperties => {
      if (flash && !isValNullOrNA) {
        const customFlashColor = posMasterTable.getFlashColor(row, col.key, flash, getRow);
        if (customFlashColor) {
          return {
            backgroundColor: customFlashColor,
            color: "#FFFFFF",
            transition: "background-color 0.05s ease, color 0.05s ease",
          };
        }
        // undefined means "no flash" for this column — fall through to normal style
      }
      return {
        color: isParent && !flash ? (baseColor === colors.textMuted ? colors.textSecondary : baseColor) : baseColor,
        backgroundColor: cellBgColor || "transparent",
        transition: "background-color 0.05s ease, color 0.05s ease",
      };
    };

    // Ticker/first-col decoration
    const isTickerCol = col.key === "ticker";

    return (
      <div
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
          // Child rows: indent only the ticker column
          paddingLeft: isTickerCol && !isParent ? 25 : 8,
          paddingRight: 8,
          fontSize: isParent ? config.fontSize : config.fontSize,
          fontWeight: isParent ? 700 : 500,
          whiteSpace: "nowrap",
          overflow: "hidden",
          textOverflow: "ellipsis",
          borderRight: `1px solid ${colors.borderSubtle}`,
          gap: 4,
          ...getCellStyle(),
        }}
      >
        {/* Chevron toggle for parent rows (only on first column) */}
        {isFirstCol && isParent && (
          <span
            style={{
              fontSize: 11,
              fontWeight: 700,
              color: "#FFFFFF",
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              width: 14,
              height: 14,
              flexShrink: 0,
              transition: "transform 0.15s ease",
              transform: isCollapsed ? "rotate(-90deg)" : "rotate(0deg)",
              opacity: 0.85,
            }}
          >
            ▼
          </span>
        )}



        {displayVal}

        {/* Div(D) purple dot marker on ticker column */}
        {isTickerCol && row.div_d > 0 && (
          <span
            title={`Div Yield: ${(parseFloat(row.div_d) * 100).toFixed(2)}%`}
            style={{
              width: 7,
              height: 7,
              borderRadius: "50%",
              backgroundColor: "#9333EA",
              boxShadow: "0 0 8px #9333EA",
              display: "inline-block",
              marginLeft: 4,
              cursor: "help",
              flexShrink: 0,
            }}
          />
        )}
      </div>
    );
  }
);

/**
 * Calculates a fixed, non-fluctuating column width based on the column's defined widthPx
 * and header text length. Does NOT depend on live row data lengths so columns never fluctuate.
 */
export function calculateOptimalColumnWidth(col: any, _flatRows?: any[]): number {
  const minWidth = 70;
  const baseWidth = col.widthPx || 90;
  const headerText = col.header || "";
  const headerWidth = headerText.length * 8 + 24;
  return Math.max(minWidth, baseWidth, headerWidth);
}

// ─── Main component ───────────────────────────────────────────────────────────
export function PosMasterTreeView({
  data,
  hiddenColumns = [],
  lastChanges,
  posColumnGroup,
  userEmail,
}: PosMasterTreeViewProps) {
  const { getRow } = useEquityData();

  // ── Persist collapse state per user ───────────────────────────────────────
  const storageKey = userEmail
    ? `${userEmail}:posMasterCollapsed`
    : "posMasterCollapsed";

  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(() => {
    if (typeof window !== "undefined") {
      const saved = localStorage.getItem(storageKey);
      if (saved) {
        try {
          return new Set(JSON.parse(saved));
        } catch {
          // ignore
        }
      }
    }
    return new Set(); // default: all expanded
  });

  const toggleGroup = (undTicker: string) => {
    setCollapsedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(undTicker)) {
        next.delete(undTicker);
      } else {
        next.add(undTicker);
      }
      if (typeof window !== "undefined") {
        localStorage.setItem(storageKey, JSON.stringify(Array.from(next)));
      }
      return next;
    });
  };

  // ── Columns from group + hidden filter ────────────────────────────────────
  const columns = useMemo(() => {
    posMasterTable.activeGroup = posColumnGroup;
    const groupCols = posMasterTable.getColumnsByGroup(posColumnGroup);
    return groupCols.filter((c) => !hiddenColumns.includes(c.key));
  }, [posColumnGroup, hiddenColumns]);

  // ── Layout mode ──
  const isFlexLayout = posColumnGroup !== "overview" && columns.length <= 20;

  // ── Build flat tree ───────────────────────────────────────────────────────
  const flatRows = useMemo((): FlatRow[] => {
    const parentRows = new Map<string, any>(); // undTicker → stock row (from Hedge acct)
    const childrenMap = new Map<string, any[]>(); // undTicker → CW rows (from MM acct)

    for (const row of data) {
      const ticker = String(row.ticker ?? "").toUpperCase();
      const undTicker = String(row.und_ticker ?? "").toUpperCase();

      if (ticker === undTicker) {
        // Underlying stock row (hedge account)
        parentRows.set(ticker, row);
      } else {
        // CW row (MM account) → group under its und_ticker
        if (!childrenMap.has(undTicker)) childrenMap.set(undTicker, []);
        childrenMap.get(undTicker)!.push(row);
      }
    }

    // Collect all underlyings, sorted alphabetically
    const allUnderlyings = Array.from(
      new Set([...parentRows.keys(), ...childrenMap.keys()])
    ).sort();

    // Assign accent colors
    const accentMap = new Map<string, string>(
      allUnderlyings.map((und, i) => [und, ACCENT_PALETTE[i % ACCENT_PALETTE.length]])
    );

    const result: FlatRow[] = [];

    for (const undTicker of allUnderlyings) {
      const children = (childrenMap.get(undTicker) ?? []).sort((a, b) =>
        String(a.ticker).localeCompare(String(b.ticker))
      );
      let parent = parentRows.get(undTicker);
      const accentColor = accentMap.get(undTicker) ?? colors.increase;

      if (parent) {
        // Real hedging stock row — add aggregated CW sub-totals alongside its own data
        const sumOfVal = (field: string) =>
          children.reduce((s, r) => s + (Number(r[field]) || 0), 0);
        parent = {
          ...parent,
          balance: (Number(parent.balance) || 0) + sumOfVal("balance"),
          balance_t_1: (Number(parent.balance_t_1) || 0) + sumOfVal("balance_t_1"),
          bought_qty: (Number(parent.bought_qty) || 0) + sumOfVal("bought_qty"),
          bought_amt: (Number(parent.bought_amt) || 0) + sumOfVal("bought_amt"),
          sold_qty: (Number(parent.sold_qty) || 0) + sumOfVal("sold_qty"),
          sold_amt: (Number(parent.sold_amt) || 0) + sumOfVal("sold_amt"),
          delta_lots_t: (Number(parent.delta_lots_t) || 0) + sumOfVal("delta_lots_t"),
          delta_cash_t: (Number(parent.delta_cash_t) || 0) + sumOfVal("delta_cash_t"),
          delta_cash_t_1: (Number(parent.delta_cash_t_1) || 0) + sumOfVal("delta_cash_t_1"),
          trd_delta_lots_t: (Number(parent.trd_delta_lots_t) || 0) + sumOfVal("trd_delta_lots_t"),
          trd_delta_cash_t: (Number(parent.trd_delta_cash_t) || 0) + sumOfVal("trd_delta_cash_t"),
          cash_vega_t: sumOfVal("cash_vega_t"),
          cash_theta_t: sumOfVal("cash_theta_t"),
          position_pnl_mtm: (Number(parent.position_pnl_mtm) || 0) + sumOfVal("position_pnl_mtm"),
          trading_pnl_mtm: (Number(parent.trading_pnl_mtm) || 0) + sumOfVal("trading_pnl_mtm"),
          total_pnl_mtm: (Number(parent.total_pnl_mtm) || 0) + sumOfVal("total_pnl_mtm"),
          position_pnl_theo: (Number(parent.position_pnl_theo) || 0) + sumOfVal("position_pnl_theo"),
          trading_pnl_theo: (Number(parent.trading_pnl_theo) || 0) + sumOfVal("trading_pnl_theo"),
          total_pnl_theo: (Number(parent.total_pnl_theo) || 0) + sumOfVal("total_pnl_theo"),
          delta_pnl: (Number(parent.delta_pnl) || 0) + sumOfVal("delta_pnl"),
          gamma_pnl: (Number(parent.gamma_pnl) || 0) + sumOfVal("gamma_pnl"),
          theta_pnl: (Number(parent.theta_pnl) || 0) + sumOfVal("theta_pnl"),
          total_pnl_theo_cum: (Number(parent.total_pnl_theo_cum) || 0) + sumOfVal("total_pnl_theo_cum"),
          total_pnl_mtm_cum: (Number(parent.total_pnl_mtm_cum) || 0) + sumOfVal("total_pnl_mtm_cum"),
          _cwTotalPnlMtm: sumOfVal("total_pnl_mtm"),
          _cwTotalPnlTheo: sumOfVal("total_pnl_theo"),
          _cwDeltaCash: sumOfVal("delta_cash_t"),
        };

        // Push parent row only if underlying stock was traded
        result.push({ row: parent, isParent: true, undTicker, accentColor });

        // Push children if group is not collapsed
        if (!collapsedGroups.has(undTicker)) {
          for (const child of children) {
            result.push({ row: child, isParent: false, undTicker, accentColor });
          }
        }
      } else {
        // Underlying stock was NOT traded — do NOT synthesize or show parent row.
        // Show ONLY the CW rows directly.
        for (const child of children) {
          result.push({ row: child, isParent: false, undTicker, accentColor });
        }
      }
    }

    return result;
  }, [data, collapsedGroups, getRow]);

  // ── Compute Optimal Column Widths dynamically ──
  const columnWidths = useMemo(() => {
    const widths: Record<string, number> = {};
    columns.forEach((col) => {
      widths[col.key] = calculateOptimalColumnWidth(col);
    });
    return widths;
  }, [columns]);

  const totalColumnsWidth = useMemo(() => {
    return columns.reduce((sum, col) => {
      const rawWidth = columnWidths[col.key] || 85;
      return sum + rawWidth + 20;
    }, 0);
  }, [columns, columnWidths]);

  const tableWidthStyle = isFlexLayout ? "100%" : `${totalColumnsWidth}px`;

  const tableMinWidthStyle = useMemo(() => {
    const minWidthSum = columns.reduce((sum, col) => {
      const rawWidth = columnWidths[col.key] || 85;
      const minVal = isFlexLayout ? Math.max(rawWidth - 5, 50) : rawWidth + 20;
      return sum + minVal;
    }, 0);
    return `${minWidthSum}px`;
  }, [columns, columnWidths, isFlexLayout]);

  // ── Flash tracking ────────────────────────────────────────────────────────
  const activeFlashesRef = useRef<Map<string, { dir: "up" | "down"; expire: number }>>(
    new Map()
  );

  const currentFlashes = useMemo(() => {
    const now = Date.now();
    const map = activeFlashesRef.current;

    if (lastChanges && lastChanges.size > 0) {
      lastChanges.forEach((dir, key) => {
        map.set(key, { dir, expire: now + FLASH_DURATION });
      });
    }

    const result = new Map<string, "up" | "down">();
    for (const [key, val] of map.entries()) {
      if (now > val.expire) {
        map.delete(key);
      } else {
        result.set(key, val.dir);
      }
    }
    return result;
  }, [lastChanges]);

  // ── Scroll / virtualization ───────────────────────────────────────────────
  const containerRef = useRef<HTMLDivElement>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [containerHeight, setContainerHeight] = useState(600);

  useLayoutEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) setContainerHeight(entry.contentRect.height);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const rowHeight = tableConfig.rowHeight;
  const headerHeight = tableConfig.headerHeight;
  const bufferRows = 6;

  const startIndex = Math.max(0, Math.floor(scrollTop / rowHeight) - bufferRows);
  const visibleCount = Math.ceil(containerHeight / rowHeight);
  const endIndex = Math.min(
    flatRows.length,
    startIndex + visibleCount + bufferRows * 2
  );

  // ── Render ────────────────────────────────────────────────────────────────
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
        onScroll={(e) => setScrollTop(e.currentTarget.scrollTop)}
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
        {/* ── Sticky header ── */}
        <div
          style={{
            display: "flex",
            height: headerHeight,
            backgroundColor: "#101010",
            borderBottom: `1px solid ${colors.borderSubtle}`,
            position: "sticky",
            top: 0,
            zIndex: 200,
            width: tableWidthStyle,
            minWidth: tableMinWidthStyle,
          }}
        >
          {columns.map((col) => (
            <HeaderCell
              key={col.key}
              col={col}
              width={columnWidths[col.key] || 85}
              isFlexLayout={isFlexLayout}
            />
          ))}
        </div>

        {/* ── Virtualized body ── */}
        <div
          style={{
            position: "relative",
            height: flatRows.length * rowHeight,
            width: tableWidthStyle,
            minWidth: tableMinWidthStyle,
            boxSizing: "content-box",
          }}
        >
          {flatRows.length === 0 ? (
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
                fontSize: 12,
                fontStyle: "italic",
              }}
            >
              No position data
            </div>
          ) : (
            flatRows.slice(startIndex, endIndex).map((item, relIdx) => {
              const absIdx = startIndex + relIdx;
              const rowKey = `${item.row.ticker}-${item.isParent ? "parent" : "child"}`;

              return (
                <div
                  key={rowKey}
                  onClick={item.isParent ? () => toggleGroup(item.undTicker) : undefined}
                  style={{
                    position: "absolute",
                    top: 0,
                    left: 0,
                    width: tableWidthStyle,
                    minWidth: tableMinWidthStyle,
                    height: rowHeight,
                    transform: `translateY(${absIdx * rowHeight}px) translateZ(0)`,
                    willChange: "transform",
                    display: "flex",
                    alignItems: "stretch",
                    // Parent rows: elevated bg; children: standard bg
                    backgroundColor: item.isParent
                      ? "rgba(255, 255, 255, 0.04)"
                      : "transparent",
                    // Child rows: inset left accent strip — default white
                    boxShadow: item.isParent
                      ? "none"
                      : "inset 2px 0 0 #FFFFFF",
                    borderBottom: `1px solid ${colors.borderSubtle}`,
                    cursor: item.isParent ? "pointer" : "default",
                    boxSizing: "border-box",
                    transition: "background-color 0.12s ease",
                  }}
                  onMouseEnter={(e) => {
                    if (item.isParent) {
                      (e.currentTarget as HTMLDivElement).style.backgroundColor =
                        "rgba(255, 255, 255, 0.07)";
                    } else {
                      (e.currentTarget as HTMLDivElement).style.backgroundColor =
                        "rgba(255, 255, 255, 0.02)";
                    }
                  }}
                  onMouseLeave={(e) => {
                    (e.currentTarget as HTMLDivElement).style.backgroundColor = item.isParent
                      ? "rgba(255, 255, 255, 0.04)"
                      : "transparent";
                  }}
                >
                  {columns.map((col, cIdx) => {
                    const cellKey = `${item.row.ticker}:${col.key}`;
                    const flashDir = currentFlashes.get(cellKey);

                    return (
                      <TreeCell
                        key={col.key}
                        col={col}
                        row={item.row}
                        width={columnWidths[col.key] || 85}
                        isParent={item.isParent}
                        isFirstCol={cIdx === 0}
                        isCollapsed={collapsedGroups.has(item.undTicker)}
                        accentColor={item.accentColor}
                        flash={flashDir}
                        isFlexLayout={isFlexLayout}
                      />
                    );
                  })}
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}
