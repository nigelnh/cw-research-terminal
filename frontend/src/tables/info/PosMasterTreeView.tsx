/**
 * PosMasterTreeView — Hierarchical tree-table for Position Master
 *
 * Groups CW rows (MM account, und_ticker !== ticker) as children under their
 * underlying stock rows (Hedge account, und_ticker === ticker) as parents.
 * If no hedging row exists for an underlying, a synthetic parent is created
 * from aggregated child data and live WebSocket equity prices.
 */

import React, { useState, useRef, useLayoutEffect, useMemo } from "react";
import { posMasterTable } from "./PosMasterTable";
import type { PosColumnGroup } from "./PosMasterTable";
import { colors, tableConfig } from "@/design/tokens";
import { useEquityData } from "@/data/useEquityData";

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
    isFlexLayout,
  }: {
    col: any;
    isFlexLayout: boolean;
  }) => {
    const config = posMasterTable.config;

    const getColumnStyle = (): React.CSSProperties => {
      const baseWidth = 85;
      const rawWidth = col.widthPx || (col.flex ? col.flex * baseWidth : baseWidth);
      if (isFlexLayout) {
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
      const baseWidth = 85;
      const rawWidth = col.widthPx || (col.flex ? col.flex * baseWidth : baseWidth);
      if (isFlexLayout) {
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

    const getCellStyle = (): React.CSSProperties => {
      if (flash) {
        const customFlashColor = posMasterTable.getFlashColor(row, col.key, flash, getRow);
        if (customFlashColor) {
          return {
            backgroundColor: customFlashColor,
            color: "#FFFFFF",
            transition: "background-color 0.05s ease, color 0.05s ease",
          };
        }
        return {
          backgroundColor: flash === "up" ? colors.increase : colors.decrease,
          color: "#FFFFFF",
          transition: "background-color 0.05s ease, color 0.05s ease",
        };
      }
      return {
        color: isParent && !flash ? (baseColor === colors.textMuted ? colors.textSecondary : baseColor) : baseColor,
        backgroundColor: cellBgColor || "transparent",
        transition: "background-color 0.05s ease, color 0.05s ease",
      };
    };

    const displayVal = col.getDisplayValue(row);

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

  // ── Layout mode ───────────────────────────────────────────────────────────
  const isFlexLayout = columns.length <= 20;
  const baseWidth = 85;
  const totalColumnsWidth = columns.reduce((sum, col) => {
    const rawWidth = col.widthPx || (col.flex ? col.flex * baseWidth : baseWidth);
    return sum + rawWidth + 20;
  }, 0);
  const tableWidthStyle = isFlexLayout ? "100%" : `${totalColumnsWidth}px`;

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

      if (!parent) {
        // Synthesize parent from live equity data + aggregated child values
        const liveStock = getRow(undTicker);
        const lastPrcT =
          liveStock?.Traded && liveStock.Traded > 0
            ? liveStock.Traded
            : liveStock?.Ref ?? null;
        const lastPrcT1 = liveStock?.Ref ?? null;

        const sumOf = (field: string) =>
          children.reduce((s, r) => s + (Number(r[field]) || 0), 0) || null;

        parent = {
          ticker: undTicker,
          und_ticker: undTicker,
          Symbol: undTicker,
          last_prc_t: lastPrcT,
          last_prc_t_1: lastPrcT1,
          spot_prc_s: lastPrcT,
          net_chg_pct:
            lastPrcT && lastPrcT1 && lastPrcT1 > 0
              ? lastPrcT / lastPrcT1 - 1
              : null,
          // Aggregated financial fields
          balance: sumOf("balance"),
          balance_t_1: sumOf("balance_t_1"),
          total_pnl_mtm: sumOf("total_pnl_mtm"),
          total_pnl_theo: sumOf("total_pnl_theo"),
          total_pnl_mtm_cum: sumOf("total_pnl_mtm_cum"),
          total_pnl_theo_cum: sumOf("total_pnl_theo_cum"),
          delta_cash_t: sumOf("delta_cash_t"),
          // CW-specific fields: null (formatters will display "")
          expiry: null,
          dte: null,
          tte_t: null,
          tte_t_1: null,
          strike_k: null,
          multiplier_m: null,
          cvr: null,
          hedge_v_t: null,
          hedge_v_t_1: null,
          rate: null,
          div_d: null,
          fund: null,
          sold_amt: null,
          sold_qty: null,
          sold_avg: null,
          bought_amt: null,
          bought_qty: null,
          bought_avg: null,
          theo_prc_t: null,
          theo_prc_t_1: null,
          delta_t: null,
          delta_lots_t: null,
          delta_cash_t_1: null,
          trd_delta_lots_t: null,
          trd_delta_cash_t: null,
          gamma_amt_pct_t: null,
          vega_pct_t: null,
          cash_vega_t: null,
          theta_t: null,
          cash_theta_t: null,
          trading_pnl_theo: null,
          position_pnl_theo: null,
          delta_pnl: null,
          gamma_pnl: null,
          theta_pnl: null,
          vega_pnl: null,
          unexplained_pnl: null,
          capital_cost: null,
          position_pnl_mtm: null,
          trading_pnl_mtm: null,
          _isSynthetic: true,
        };
      } else {
        // Real hedging row — add aggregated CW sub-totals alongside its own data
        const sumOf = (field: string) =>
          children.reduce((s, r) => s + (Number(r[field]) || 0), 0);
        parent = {
          ...parent,
          // For a real hedging row (stock), also add CW position summaries
          // so the parent row gives a holistic view of that underlying group
          _cwTotalPnlMtm: sumOf("total_pnl_mtm"),
          _cwTotalPnlTheo: sumOf("total_pnl_theo"),
          _cwDeltaCash: sumOf("delta_cash_t"),
        };
      }

      // Push parent row
      result.push({ row: parent, isParent: true, undTicker, accentColor });

      // Push children if group is not collapsed
      if (!collapsedGroups.has(undTicker)) {
        for (const child of children) {
          result.push({ row: child, isParent: false, undTicker, accentColor });
        }
      }
    }

    return result;
  }, [data, collapsedGroups, getRow]);

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
            minWidth: tableWidthStyle,
          }}
        >
          {columns.map((col) => (
            <HeaderCell key={col.key} col={col} isFlexLayout={isFlexLayout} />
          ))}
        </div>

        {/* ── Virtualized body ── */}
        <div
          style={{
            position: "relative",
            height: flatRows.length * rowHeight,
            width: tableWidthStyle,
            minWidth: tableWidthStyle,
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
                    minWidth: tableWidthStyle,
                    height: rowHeight,
                    transform: `translateY(${absIdx * rowHeight}px) translateZ(0)`,
                    willChange: "transform",
                    display: "flex",
                    alignItems: "stretch",
                    // Parent rows: elevated bg; children: standard bg
                    backgroundColor: item.isParent
                      ? "rgba(255, 255, 255, 0.04)"
                      : "transparent",
                    // Child rows: inset left accent strip — no layout shift (unlike borderLeft)
                    boxShadow: item.isParent
                      ? "none"
                      : `inset 2px 0 0 ${item.accentColor}66`,
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
