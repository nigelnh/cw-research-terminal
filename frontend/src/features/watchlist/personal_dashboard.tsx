import { Fragment, useMemo, useRef, useState } from "react";
import type { WatchlistItem } from "@/domain/models";
import { useWatchlist } from "@/data/watchlist";
import { useResearchMarket } from "@/data/use_research_market";
import { useDashboardData } from "@/data/query/use_dashboard_data";
import { QUOTE_COLUMNS, QUOTE_COLUMN_HINTS, quoteCell, type QuoteColumnKey } from "@/components/common/quote_columns";
import { completeOrder, moveGroupedRows, useWatchlistLayout } from "@/components/common/watchlist_layout";
import { useInstrumentSpecs } from "@/data/instruments/use_instrument_specs";
import { MarketOverviewStrip } from "./market_overview_strip";
import {
  EMPTY_FILTER,
  RegistryFilter,
  rowMatchesFilter,
  type FilterState,
} from "@/components/common/registry_filter";
import {
  DASH,
  DismissCell,
  DismissHeader,
  HiddenNote,
  PinCell,
  PinHeader,
  dteDisplay,
  dteNumber,
  useHiddenRows,
  useSortPin,
  type SortFields,
} from "@/components/common/grid_table";

interface PersonalDashboardProps {
  onNavigateToUniverse?: () => void;
  selectedSymbol?: string | null;
  onSelectSymbol?: (symbol: string | null) => void;
  filter?: string;
}

const isCwItem = (item: WatchlistItem) =>
  item.instrumentType === "CW" ||
  (item.instrumentType !== "STOCK" && item.symbol.startsWith("C") && item.symbol.length >= 6);

interface StockRow {
  symbol: string;
  ref: number | null;
  bid: number | null;
  ask: number | null;
  last: number | null;
  tradingValue: number | null;
  chgPct: number | null;
  vol: number | null;
  ceiling: number | null;
  floor: number | null;
}

interface CwRow {
  symbol: string;
  underlying: string | null;
  issuer: string | null;
  bid: number | null;
  ask: number | null;
  last: number | null;
  tradingValue: number | null;
  ref: number | null;
  ceiling: number | null;
  floor: number | null;
  chgPct: number | null;
  vol: number | null;
  strike: number | null;
  ratio: number | null;
  dte: number | null;
  dteText: string;
  lastTradingDate: string | null;
  ivBid: number | null;
  ivTrade: number | null;
  ivAsk: number | null;
  conflicting: boolean;
}

/**
 * One row in the unified watchlist table. Stock/index rows are parents; CW rows
 * are children grouped under the parent whose symbol matches `underlying`. Every
 * row uses the same column schema — CW-only fields are null on stocks and vice versa.
 */
interface UnifiedRow {
  symbol: string;
  kind: "stock" | "cw";
  issuer: string | null;
  underlying: string | null;
  ref: number | null;
  bid: number | null;
  ask: number | null;
  last: number | null;
  tradingValue: number | null;
  chgPct: number | null;
  vol: number | null;
  ceiling: number | null;
  floor: number | null;
  strike: number | null;
  ratio: number | null;
  dteText: string;
  lastTradingDate: string | null;
  dte: number | null;
  ivBid: number | null;
  ivTrade: number | null;
  ivAsk: number | null;
  conflicting: boolean;
}

const UNIFIED_FIELDS: SortFields<UnifiedRow> = {
  symbol: (r) => r.symbol,
  issuer: (r) => r.issuer,
  ceiling: (r) => r.ceiling,
  floor: (r) => r.floor,
  ref: (r) => r.ref,
  bid: (r) => r.bid,
  ask: (r) => r.ask,
  last: (r) => r.last,
  tradingValue: (r) => r.tradingValue,
  change: (r) => r.last !== null && r.ref !== null ? r.last - r.ref : null,
  lastTradingDate: (r) => r.lastTradingDate,
  chgPct: (r) => r.chgPct,
  vol: (r) => r.vol,
  strike: (r) => r.strike,
  ratio: (r) => r.ratio,
  dte: (r) => r.dte,
  ivBid: (r) => r.ivBid,
  ivTrade: (r) => r.ivTrade,
  ivAsk: (r) => r.ivAsk,
};

const TD: React.CSSProperties = { padding: "0 8px", textAlign: "right" };
const ROW_BORDER = "1px solid var(--border-row)";

export function PersonalDashboard({
  onNavigateToUniverse,
  selectedSymbol = null,
  onSelectSymbol,
  filter = "",
}: PersonalDashboardProps) {
  const { items } = useWatchlist();
  const { quotes, warrants } = useResearchMarket();
  const { getSpec } = useInstrumentSpecs();
  const [filterState, setFilterState] = useState<FilterState>(EMPTY_FILTER);
  const hiddenRows = useHiddenRows();

  const allSymbols = useMemo(() => items.map((i) => i.symbol), [items]);
  const { getRow } = useDashboardData(allSymbols);

  const setSelected = onSelectSymbol ?? (() => {});
  const q = filter.trim().toUpperCase().replace(/^\//, "").trim();
  const textMatch = (sym: string, und?: string | null) =>
    !q || sym.toUpperCase().includes(q) || (und ?? "").toUpperCase().includes(q);

  const stockRows: StockRow[] = useMemo(
    () =>
      items
        .filter((i) => !isCwItem(i))
        .map((item) => {
          const row = getRow(item.symbol);
          const quote = row?.quote ?? quotes.get(item.symbol.toUpperCase());
          const pct =
            typeof quote?.priceChangePercent === "number" ? quote.priceChangePercent * 100 : null;
          return {
            symbol: item.symbol,
            ref: quote?.referencePrice ?? null,
            bid: quote?.bidPrice ?? null,
            ask: quote?.askPrice ?? null,
            last: quote?.lastPrice ?? null,
            tradingValue: quote?.tradingValue ?? null,
            chgPct: pct,
            vol: quote?.totalVolume ?? null,
            ceiling: quote?.ceilingPrice ?? null,
            floor: quote?.floorPrice ?? null,
          };
        })
        .filter((r) => textMatch(r.symbol))
        .filter((r) => !hiddenRows.isHidden(r.symbol)),
    [items, getRow, quotes, q, hiddenRows],
  );

  const unfilteredCwRows: CwRow[] = useMemo(
    () =>
      items
        .filter(isCwItem)
        .map((item) => {
          const row = getRow(item.symbol);
          const quote = row?.quote ?? quotes.get(item.symbol.toUpperCase());
          const cw = warrants.get(item.symbol.toUpperCase());
          const fb = row?.analytics ?? null;
          const spec = getSpec(item.symbol);
          const underlying = spec?.underlyingSymbol || item.underlyingSymbol || cw?.underlyingSymbol || null;
          const last = quote?.lastPrice ?? cw?.quote?.lastPrice ?? null;
          const pctRaw = quote?.priceChangePercent ?? cw?.quote?.priceChangePercent ?? null;
          const lastTradingDate = spec?.lastTradingDate ?? null;
          const maturityDate = spec?.maturityDate ?? null;
          return {
            symbol: item.symbol,
            underlying,
            issuer: spec?.issuer ?? null,
            bid: quote?.bidPrice ?? cw?.quote?.bidPrice ?? null,
            ask: quote?.askPrice ?? cw?.quote?.askPrice ?? null,
            last,
            tradingValue: quote?.tradingValue ?? cw?.quote?.tradingValue ?? null,
            ref: quote?.referencePrice ?? cw?.quote?.referencePrice ?? null,
            ceiling: quote?.ceilingPrice ?? cw?.quote?.ceilingPrice ?? null,
            floor: quote?.floorPrice ?? cw?.quote?.floorPrice ?? null,
            chgPct: typeof pctRaw === "number" ? pctRaw * 100 : null,
            vol: quote?.totalVolume ?? cw?.quote?.totalVolume ?? null,
            strike: spec?.strikePrice ?? null,
            ratio: typeof spec?.exerciseRatio === "number" ? spec.exerciseRatio : null,
            dte: dteNumber(lastTradingDate, maturityDate, fb?.dte),
            dteText: dteDisplay(lastTradingDate, maturityDate, fb?.dte),
            lastTradingDate,
            ivBid: cw?.ivBid ?? fb?.ivBid ?? null,
            ivTrade: cw?.ivTrade ?? fb?.ivTrade ?? null,
            ivAsk: cw?.ivAsk ?? fb?.ivAsk ?? null,
            conflicting: spec?.metadataVerification === "CONFLICTING",
          };
        })
        .filter((r) => textMatch(r.symbol, r.underlying))
        .filter((r) => !hiddenRows.isHidden(r.symbol)),
    [items, getRow, quotes, warrants, getSpec, q, hiddenRows],
  );

  const cwRows = useMemo(
    () => unfilteredCwRows.filter((r) => rowMatchesFilter(filterState, r)),
    [unfilteredCwRows, filterState],
  );

  const underlyingOptions = useMemo(
    () => [...new Set(unfilteredCwRows.map((r) => r.underlying).filter((v): v is string => !!v))].sort(),
    [unfilteredCwRows],
  );
  const issuerOptions = useMemo(
    () => [...new Set(unfilteredCwRows.map((r) => r.issuer).filter((v): v is string => !!v))].sort(),
    [unfilteredCwRows],
  );

  const unifiedRows: UnifiedRow[] = useMemo(
    () => [
      ...stockRows.map((s): UnifiedRow => ({
        symbol: s.symbol,
        kind: "stock",
        issuer: null,
        underlying: null,
        ref: s.ref,
        bid: s.bid,
        ask: s.ask,
        last: s.last,
        tradingValue: s.tradingValue,
        chgPct: s.chgPct,
        vol: s.vol,
        ceiling: s.ceiling,
        floor: s.floor,
        strike: null,
        ratio: null,
        dteText: DASH,
        lastTradingDate: null,
        dte: null,
        ivBid: null,
        ivTrade: null,
        ivAsk: null,
        conflicting: false,
      })),
      ...cwRows.map((c): UnifiedRow => ({
        symbol: c.symbol,
        kind: "cw",
        issuer: c.issuer,
        underlying: c.underlying,
        ref: c.ref,
        bid: c.bid,
        ask: c.ask,
        last: c.last,
        tradingValue: c.tradingValue,
        chgPct: c.chgPct,
        vol: c.vol,
        ceiling: c.ceiling,
        floor: c.floor,
        strike: c.strike,
        ratio: c.ratio,
        dteText: c.dteText,
        lastTradingDate: c.lastTradingDate,
        dte: c.dte,
        ivBid: c.ivBid,
        ivTrade: c.ivTrade,
        ivAsk: c.ivAsk,
        conflicting: c.conflicting,
      })),
    ],
    [stockRows, cwRows],
  );

  const layout = useWatchlistLayout();
  const manuallyOrdered = useMemo(() => {
    const order = completeOrder(unifiedRows.map(r => r.symbol), layout.rows);
    return order.map(symbol => unifiedRows.find(r => r.symbol === symbol)!);
  }, [unifiedRows, layout.rows]);
  const view = useSortPin(manuallyOrdered, UNIFIED_FIELDS);
  const drag = useRef<{ type: "column"; key: QuoteColumnKey } | { type: "row"; key: string } | null>(null);
  const [dropTarget, setDropTarget] = useState<string | null>(null);
  const columns = layout.columns.map(key => QUOTE_COLUMNS.find(c => c.key === key)!);
  const endDrag = () => { drag.current = null; setDropTarget(null); };
  const moveRow = (from: string, to: string) => {
    const next = moveGroupedRows(view.ordered, from, to);
    if (!next) return;
    // Preserve hidden/filtered identities when saving a visible reorder.
    layout.setRows([...next, ...completeOrder(items.map(i => i.symbol), layout.rows).filter(s => !next.includes(s))]);
    view.clearOrder();
  };

  const stockSyms = useMemo(
    () => new Set(stockRows.map((r) => r.symbol.toUpperCase())),
    [stockRows],
  );
  const parents = view.ordered.filter((r) => r.kind === "stock");
  const orderedCws = view.ordered.filter((r) => r.kind === "cw");
  const childrenOf = (sym: string) =>
    orderedCws.filter((c) => (c.underlying ?? "").toUpperCase() === sym.toUpperCase());
  const orphanCws = orderedCws.filter(
    (c) => !c.underlying || !stockSyms.has(c.underlying.toUpperCase()),
  );

  const symbolWidth = `calc(${Math.max(8, ...unifiedRows.map((r) => r.symbol.length + (r.kind === "cw" ? 1 : 0)))}ch + 24px)`;
  const renderRow = (r: UnifiedRow) => {
    const selected = selectedSymbol === r.symbol;
    return (
      <tr
        key={r.symbol}
        data-symbol={r.symbol}
        className={`watchlist-row${r.kind === "cw" ? " watchlist-cw" : ""}${dropTarget === r.symbol ? " is-drop-target" : ""}`}
        tabIndex={0}
        draggable
        title="Drag to reorder; Alt + ↑/↓ to move"
        onDragStart={(e) => {
          if ((e.target as HTMLElement).closest("button")) { e.preventDefault(); return; }
          drag.current = { type: "row", key: r.symbol };
          e.dataTransfer.effectAllowed = "move";
          e.dataTransfer.setData("text/plain", r.symbol);
        }}
        onDragOver={(e) => {
          if (drag.current?.type !== "row" || !moveGroupedRows(view.ordered, drag.current.key, r.symbol)) return;
          e.preventDefault(); e.dataTransfer.dropEffect = "move"; setDropTarget(r.symbol);
        }}
        onDrop={(e) => {
          e.preventDefault();
          if (drag.current?.type === "row") moveRow(drag.current.key, r.symbol);
          endDrag();
        }}
        onDragEnd={endDrag}
        onClick={() => { if (!drag.current) setSelected(r.symbol); }}
        onKeyDown={(e) => {
          if (e.target !== e.currentTarget) return;
          if (e.key === "Enter") { e.preventDefault(); setSelected(r.symbol); }
          if (e.altKey && (e.key === "ArrowUp" || e.key === "ArrowDown")) {
            e.preventDefault();
            const peers = view.ordered.filter(other => other.kind === r.kind && (r.kind === "stock" || other.underlying === r.underlying));
            const to = peers[peers.findIndex(other => other.symbol === r.symbol) + (e.key === "ArrowUp" ? -1 : 1)];
            if (to) moveRow(r.symbol, to.symbol);
          }
        }}
        style={{
          cursor: "pointer",
          height: 26,
          background: selected ? "var(--panel-3)" : r.kind === "cw" ? "var(--panel-2)" : "var(--bg)",
          borderBottom: ROW_BORDER,
        }}
      >
        <PinCell symbol={r.symbol} fill={view.pinFill(r.symbol)} onToggle={view.togglePin} />
        {columns.map(column => {
          const cell = quoteCell(r, column.key);
          return column.key === "symbol" ? (
            <td key={column.key} style={{ padding: "0 8px", paddingLeft: r.kind === "cw" ? "calc(8px + 1ch)" : 8, color: r.kind === "cw" ? "var(--t-92)" : "var(--accent)", whiteSpace: "nowrap" }}>
              {r.symbol}
              {r.conflicting && <span title="Conflicting metadata — quant withheld" style={{ marginLeft: 5, color: "var(--down)" }}>◆</span>}
            </td>
          ) : <td key={column.key} title={QUOTE_COLUMN_HINTS[column.key]} style={{ ...TD, color: cell.color }}>{r.kind === "stock" && ["strike", "ratio", "lastTradingDate", "dte", "issuer"].includes(column.key) ? null : cell.text}</td>;
        })}
        <DismissCell symbol={r.symbol} onDismiss={hiddenRows.hide} />
      </tr>
    );
  };

  return (
    <div>
      <MarketOverviewStrip />
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 12,
          marginBottom: 14,
          position: "relative",
        }}
      >
        <span className="heading" style={{ fontSize: 14, fontWeight: 700, letterSpacing: "0.02em" }}>
          Watchlist
        </span>
        <HiddenNote count={hiddenRows.count} onReset={hiddenRows.reset} />
        <RegistryFilter
          underlyingOptions={underlyingOptions}
          issuerOptions={issuerOptions}
          value={filterState}
          onChange={setFilterState}
        />
      </div>

      {items.length === 0 && (
        <p style={{ padding: "56px 0", textAlign: "center", fontSize: 12, color: "var(--t-46)" }}>
          No instruments watched. Add one from{" "}
          {onNavigateToUniverse ? (
            <button
              type="button"
              onClick={onNavigateToUniverse}
              className="focus-ring"
              style={{
                background: "transparent",
                border: "none",
                cursor: "pointer",
                textDecoration: "underline",
                font: "inherit",
                color: "var(--accent)",
              }}
            >
              Research
            </button>
          ) : (
            "Research"
          )}
          .
        </p>
      )}

      {(stockRows.length > 0 || cwRows.length > 0) && (
        <div className="watchlist-table-scroll">
        <table
          className="mono grid-lined watchlist-table"
          style={{ width: "100%", borderCollapse: "collapse", fontSize: 11.5 }}
        >
          <thead>
            <tr style={{ borderBottom: "1px solid var(--border-strong)" }}>
              <PinHeader />
              {columns.map((column, index) => (
                <th key={column.key} draggable tabIndex={0}
                  data-column={column.key}
                  className={dropTarget === column.key ? "is-drop-target" : undefined}
                  aria-sort={view.sortMark(column.key) === "▲" ? "ascending" : view.sortMark(column.key) === "▼" ? "descending" : "none"}
                  title={`${QUOTE_COLUMN_HINTS[column.key] ? `${QUOTE_COLUMN_HINTS[column.key]} · ` : ""}Click to sort · Drag to reorder · Alt + ←/→ to move`}
                  style={{ padding: "5px 8px", textAlign: column.key === "symbol" ? "left" : "right", width: column.key === "symbol" ? symbolWidth : column.key === "lastTradingDate" ? "1%" : undefined, color: "var(--t-50)", fontWeight: 500, cursor: "grab", userSelect: "none" }}
                  onClick={() => { if (!drag.current) view.toggleSort(column.key); }}
                  onDragStart={(e) => { drag.current = { type: "column", key: column.key }; e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", column.key); }}
                  onDragOver={(e) => { if (drag.current?.type === "column") { e.preventDefault(); e.dataTransfer.dropEffect = "move"; setDropTarget(column.key); } }}
                  onDrop={(e) => { e.preventDefault(); if (drag.current?.type === "column") layout.moveColumn(drag.current.key, column.key); endDrag(); }}
                  onDragEnd={endDrag}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); view.toggleSort(column.key); }
                    if (e.altKey && (e.key === "ArrowLeft" || e.key === "ArrowRight")) {
                      e.preventDefault();
                      const to = columns[index + (e.key === "ArrowLeft" ? -1 : 1)];
                      if (to) layout.moveColumn(column.key, to.key);
                    }
                  }}>
                  <span className="watchlist-column-label" style={{ flexDirection: column.key === "symbol" ? "row" : "row-reverse" }}>
                    <span>{column.label}</span>
                    <svg className="watchlist-sort-icon" aria-hidden="true" viewBox="0 0 12 12" fill="currentColor"
                      style={{ visibility: view.sortMark(column.key) ? "visible" : "hidden" }}>
                      <path d={view.sortMark(column.key) === "▼" ? "M1 2h10L6 11Z" : "M1 10h10L6 1Z"} />
                    </svg>
                  </span>
                </th>
              ))}
              <DismissHeader />
            </tr>
          </thead>
          <tbody>
            {parents.map((p) => (
              <Fragment key={p.symbol}>
                {renderRow(p)}
                {childrenOf(p.symbol).map(renderRow)}
              </Fragment>
            ))}
            {orphanCws.map(renderRow)}
          </tbody>
        </table>
        </div>
      )}
    </div>
  );
}
