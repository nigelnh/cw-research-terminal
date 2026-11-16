import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { RealtimePulseMap, WatchlistItem } from "@/domain/models";
import { useWatchlist } from "@/data/watchlist";
import { useResearchMarket } from "@/data/use_research_market";
import { useDashboardData } from "@/data/query/use_dashboard_data";
import {
  QUOTE_COLUMNS,
  QUOTE_COLUMN_HINTS,
  QUOTE_COLUMN_PULSE_FIELD,
  STOCK_BOARD_COLUMNS,
  watchlistCell,
  type QuoteColumnKey,
  type StockBoardColumnKey,
  type WatchlistColumnKey,
} from "@/components/common/quote_columns";
import { completeOrder, moveGroupedRows, useWatchlistLayout } from "@/components/common/watchlist_layout";
import { useInstrumentSpecs } from "@/data/instruments/use_instrument_specs";
import { MarketOverviewStrip } from "./market_overview_strip";
import { WatchlistSymbolSearch, matchingSymbols, prioritizeWatchlist, type WatchlistSearchOption } from "./watchlist_symbol_search";
import { InstrumentKindToggle, type InstrumentKindView } from "./instrument_kind_toggle";
import { useStockProfiles } from "@/data/query/use_stock_profiles";
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
import { RealtimeValue } from "@/components/common/realtime_value";

interface PersonalDashboardProps {
  onNavigateToUniverse?: () => void;
  selectedSymbol?: string | null;
  onSelectSymbol?: (symbol: string | null) => void;
  filter?: string;
}

const isCwItem = (item: WatchlistItem) =>
  item.instrumentType === "CW" ||
  (item.instrumentType !== "STOCK" && item.symbol.startsWith("C") && item.symbol.length >= 6);

/** The STOCK view's price-board values: depth either side, session range, foreign flow. */
interface BoardValues {
  bid2: number | null;
  bid3: number | null;
  ask2: number | null;
  ask3: number | null;
  bidQty: number | null;
  bid2Qty: number | null;
  bid3Qty: number | null;
  askQty: number | null;
  ask2Qty: number | null;
  ask3Qty: number | null;
  high: number | null;
  low: number | null;
  foreignBuy: number | null;
  foreignSell: number | null;
  foreignRoom: number | null;
}

const NO_BOARD_VALUES: BoardValues = {
  bid2: null, bid3: null, ask2: null, ask3: null,
  bidQty: null, bid2Qty: null, bid3Qty: null, askQty: null, ask2Qty: null, ask3Qty: null,
  high: null, low: null, foreignBuy: null, foreignSell: null, foreignRoom: null,
};

interface StockRow extends BoardValues {
  symbol: string;
  ref: number | null;
  bid: number | null;
  ask: number | null;
  last: number | null;
  tradedQuantity: number | null;
  change: number | null;
  chgPct: number | null;
  vol: number | null;
  ceiling: number | null;
  floor: number | null;
  pulses?: RealtimePulseMap;
  trackedRealtime: boolean;
}

interface CwRow {
  symbol: string;
  underlying: string | null;
  issuer: string | null;
  bid: number | null;
  ask: number | null;
  last: number | null;
  tradedQuantity: number | null;
  change: number | null;
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
  pulses?: RealtimePulseMap;
  trackedRealtime: boolean;
}

/**
 * One row in the unified watchlist table. Stock/index rows are parents; CW rows
 * are children grouped under the parent whose symbol matches `underlying`. Every
 * row uses the same column schema — CW-only fields are null on stocks and vice versa.
 */
interface UnifiedRow extends BoardValues {
  symbol: string;
  kind: "stock" | "cw";
  issuer: string | null;
  underlying: string | null;
  ref: number | null;
  bid: number | null;
  ask: number | null;
  last: number | null;
  tradedQuantity: number | null;
  change: number | null;
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
  pulses?: RealtimePulseMap;
  trackedRealtime: boolean;
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
  tradedQuantity: (r) => r.tradedQuantity,
  change: (r) => r.change,
  lastTradingDate: (r) => r.lastTradingDate,
  chgPct: (r) => r.chgPct,
  vol: (r) => r.vol,
  strike: (r) => r.strike,
  ratio: (r) => r.ratio,
  dte: (r) => r.dte,
  ivBid: (r) => r.ivBid,
  ivTrade: (r) => r.ivTrade,
  ivAsk: (r) => r.ivAsk,
  bid2: (r) => r.bid2,
  bid3: (r) => r.bid3,
  ask2: (r) => r.ask2,
  ask3: (r) => r.ask3,
  bidQty: (r) => r.bidQty,
  bid2Qty: (r) => r.bid2Qty,
  bid3Qty: (r) => r.bid3Qty,
  askQty: (r) => r.askQty,
  ask2Qty: (r) => r.ask2Qty,
  ask3Qty: (r) => r.ask3Qty,
  high: (r) => r.high,
  low: (r) => r.low,
  foreignBuy: (r) => r.foreignBuy,
  foreignSell: (r) => r.foreignSell,
  foreignRoom: (r) => r.foreignRoom,
};

const TD: React.CSSProperties = { padding: "0 8px", textAlign: "right" };
/**
 * Cell side padding. The STOCK price board runs 26 columns, so it uses half the padding
 * and wraps its labels (see `labelLines`) to fit a 1920px window without scrolling.
 */
const CELL_PAD = 8;
const BOARD_CELL_PAD = 4;
const ROW_BORDER = "1px solid var(--border-row)";
const TABLE_ROW_HEIGHT = 26;
const TABLE_HEADER_HEIGHT = 27;
/** The board's header holds two label lines. */
const BOARD_HEADER_HEIGHT = 41;
const VIRTUALIZE_AFTER = 80;
const VIRTUAL_OVERSCAN = 12;

/**
 * Widest value each column must show, in `ch` of the table's monospace font.
 *
 * Only the rows around the viewport are mounted (see below), so `table-layout: auto`
 * sized every column to whichever ~50 rows happened to be in the DOM: CEIL, %CHG, VOLUME
 * and RATIO changed width as you scrolled the 439-row universe. The table is now
 * `table-layout: fixed` and these budgets set the widths in a <colgroup>, so neither the
 * mounted window nor a ticking price can resize a column. Sized to the widest values in
 * the live universe (2026-11-14: 132,500 · 10,119,400 · 14.3518:1 · 100.00%) plus
 * headroom where a busier session runs longer (VOLUME to 9 digits, +/- to 5).
 */
const VALUE_CH: Record<Exclude<WatchlistColumnKey, "symbol">, number> = {
  ceiling: 7,
  floor: 7,
  ref: 7,
  bid: 7,
  ask: 7,
  last: 7,
  strike: 7,
  tradedQuantity: 9,
  change: 6,
  chgPct: 7,
  vol: 11,
  ratio: 9,
  ivBid: 6,
  ivTrade: 6,
  ivAsk: 6,
  lastTradingDate: 10,
  dte: 3,
  issuer: 5,
  // STOCK view. Depth sizes run to 1,150,500 (HPG, 2026-11-13) and their 9-char headers
  // set the width anyway; foreign room reaches 2,292,162,142 shares (HPG).
  bid2: 7,
  bid3: 7,
  ask2: 7,
  ask3: 7,
  bidQty: 10,
  bid2Qty: 10,
  bid3Qty: 10,
  askQty: 10,
  ask2Qty: 10,
  ask3Qty: 10,
  high: 7,
  low: 7,
  foreignBuy: 10,
  foreignSell: 10,
  foreignRoom: 13,
};
/** Pin dot (12px button) and dismiss × (11px button) plus their cell padding. */
const PIN_COL_WIDTH = 21;
const DISMISS_COL_WIDTH = 24;

/** The header's sort icon (1em) + its 4px gap, in ch of a 0.6em-advance mono font. */
const SORT_ICON_CH = 2.25;

/**
 * A header label's lines. On the board a label breaks after its first "_" - BID_ over
 * PRC_3 - so a column is as wide as its values rather than its 9-char name; the text is
 * unchanged. Single-word labels (CEIL, VOLUME) and the other views stay on one line.
 */
const labelLines = (label: string, wrap: boolean) => {
  const cut = label.indexOf("_") + 1;
  return wrap && cut > 0 && cut < label.length ? [label.slice(0, cut), label.slice(cut)] : [label];
};

/**
 * A column's width: its widest value (`contentCh`) or its header (longest label line +
 * 4px gap + 1em sort icon), whichever is wider, plus both side paddings and the 1px rule.
 */
const columnWidth = (label: string, contentCh: number, pad = CELL_PAD, wrap = false) => {
  const labelCh = Math.max(...labelLines(label, wrap).map(line => line.length));
  return contentCh >= labelCh + SORT_ICON_CH
    ? `calc(${contentCh}ch + ${2 * pad + 1}px)`
    : `calc(${labelCh}ch + 1em + ${2 * pad + 5}px)`;
};

export function PersonalDashboard({
  onNavigateToUniverse,
  selectedSymbol = null,
  onSelectSymbol,
  filter = "",
}: PersonalDashboardProps) {
  const { items } = useWatchlist();
  const { quotes, warrants, isRealtimeTracked, revision: marketRevision } = useResearchMarket();
  const { getSpec } = useInstrumentSpecs();
  const [filterState, setFilterState] = useState<FilterState>(EMPTY_FILTER);
  const [symbolSearch, setSymbolSearch] = useState("");
  const [kindView, setKindView] = useState<InstrumentKindView>("all");
  const hiddenRows = useHiddenRows();

  const allSymbols = useMemo(() => items.map((i) => i.symbol), [items]);
  const { getRow } = useDashboardData(allSymbols);
  const profileSymbols = useMemo(() => [...new Set(items.map(item => {
    if (!isCwItem(item)) return item.symbol;
    return getSpec(item.symbol)?.underlyingSymbol || item.underlyingSymbol || "";
  }).filter(Boolean))], [items, getSpec]);
  const { profiles } = useStockProfiles(profileSymbols);
  const profilesBySymbol = useMemo(() => new Map(profiles.map(profile => [profile.symbol, profile])), [profiles]);

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
            tradedQuantity: quote?.tradedQuantity ?? null,
            change: quote?.priceChange ?? null,
            chgPct: pct,
            vol: quote?.totalVolume ?? null,
            ceiling: quote?.ceilingPrice ?? null,
            floor: quote?.floorPrice ?? null,
            bid2: quote?.bid2Price ?? null,
            bid3: quote?.bid3Price ?? null,
            ask2: quote?.ask2Price ?? null,
            ask3: quote?.ask3Price ?? null,
            bidQty: quote?.bidQuantity ?? null,
            bid2Qty: quote?.bid2Quantity ?? null,
            bid3Qty: quote?.bid3Quantity ?? null,
            askQty: quote?.askQuantity ?? null,
            ask2Qty: quote?.ask2Quantity ?? null,
            ask3Qty: quote?.ask3Quantity ?? null,
            high: quote?.highPrice ?? null,
            low: quote?.lowPrice ?? null,
            foreignBuy: quote?.foreignBuy ?? null,
            foreignSell: quote?.foreignSell ?? null,
            foreignRoom: quote?.foreignRoom ?? null,
            pulses: quote?.realtimePulses,
            trackedRealtime: row?.trackedRealtime ?? isRealtimeTracked(item.symbol),
          };
        })
        .filter((r) => textMatch(r.symbol))
        .filter((r) => !hiddenRows.isHidden(r.symbol)),
    [items, getRow, quotes, q, hiddenRows, isRealtimeTracked, marketRevision],
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
          const last = quote?.lastPrice ?? null;
          const pctRaw = quote?.priceChangePercent ?? null;
          const lastTradingDate = spec?.lastTradingDate ?? null;
          const maturityDate = spec?.maturityDate ?? null;
          return {
            symbol: item.symbol,
            underlying,
            issuer: spec?.issuer ?? null,
            bid: quote?.bidPrice ?? null,
            ask: quote?.askPrice ?? null,
            last,
            tradedQuantity: quote?.tradedQuantity ?? null,
            change: quote?.priceChange ?? null,
            ref: quote?.referencePrice ?? null,
            ceiling: quote?.ceilingPrice ?? null,
            floor: quote?.floorPrice ?? null,
            chgPct: typeof pctRaw === "number" ? pctRaw * 100 : null,
            vol: quote?.totalVolume ?? null,
            strike: spec?.strikePrice ?? null,
            ratio: typeof spec?.exerciseRatio === "number" ? spec.exerciseRatio : null,
            dte: dteNumber(lastTradingDate, maturityDate, fb?.dte),
            dteText: dteDisplay(lastTradingDate, maturityDate, fb?.dte),
            lastTradingDate,
            ivBid: fb?.ivBid ?? null,
            ivTrade: fb?.ivTrade ?? null,
            ivAsk: fb?.ivAsk ?? null,
            conflicting: spec?.metadataVerification === "CONFLICTING",
            pulses: {
              ...(quote?.realtimePulses ?? cw?.quote?.realtimePulses ?? {}),
              ...(cw?.realtimePulses ?? {}),
            },
            trackedRealtime: row?.trackedRealtime ?? isRealtimeTracked(item.symbol),
          };
        })
        .filter((r) => textMatch(r.symbol, r.underlying))
        .filter((r) => !hiddenRows.isHidden(r.symbol)),
    [items, getRow, quotes, warrants, getSpec, q, hiddenRows, isRealtimeTracked, marketRevision],
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
        bid2: s.bid2, bid3: s.bid3, ask2: s.ask2, ask3: s.ask3,
        bidQty: s.bidQty, bid2Qty: s.bid2Qty, bid3Qty: s.bid3Qty,
        askQty: s.askQty, ask2Qty: s.ask2Qty, ask3Qty: s.ask3Qty,
        high: s.high, low: s.low,
        foreignBuy: s.foreignBuy, foreignSell: s.foreignSell, foreignRoom: s.foreignRoom,
        symbol: s.symbol,
        kind: "stock",
        issuer: null,
        underlying: null,
        ref: s.ref,
        bid: s.bid,
        ask: s.ask,
        last: s.last,
        tradedQuantity: s.tradedQuantity,
        change: s.change,
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
        pulses: s.pulses,
        trackedRealtime: s.trackedRealtime,
      })),
      ...cwRows.map((c): UnifiedRow => ({
        // The STOCK view is the only one with board columns, and it shows no warrants.
        ...NO_BOARD_VALUES,
        symbol: c.symbol,
        kind: "cw",
        issuer: c.issuer,
        underlying: c.underlying,
        ref: c.ref,
        bid: c.bid,
        ask: c.ask,
        last: c.last,
        tradedQuantity: c.tradedQuantity,
        change: c.change,
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
        pulses: c.pulses,
        trackedRealtime: c.trackedRealtime,
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
  const drag = useRef<{ type: "column"; key: WatchlistColumnKey } | { type: "row"; key: string } | null>(null);
  const [dropTarget, setDropTarget] = useState<string | null>(null);
  // STOCK is a price board with its own columns (and order); ALL and CW share the
  // warrant-oriented set.
  const stockView = kindView === "stock";
  const columns: { key: WatchlistColumnKey; label: string }[] = stockView
    ? layout.stockColumns.map(key => STOCK_BOARD_COLUMNS.find(c => c.key === key)!)
    : layout.columns.map(key => QUOTE_COLUMNS.find(c => c.key === key)!);
  const moveColumn = (from: WatchlistColumnKey, to: WatchlistColumnKey) => {
    if (stockView) layout.moveStockColumn(from as StockBoardColumnKey, to as StockBoardColumnKey);
    else layout.moveColumn(from as QuoteColumnKey, to as QuoteColumnKey);
  };
  // A sort on a column the new view does not show would order rows by something hidden.
  const columnKeys = columns.map(column => column.key).join(",");
  const { sort: activeSort, clearSort } = view;
  useEffect(() => {
    if (activeSort && !columnKeys.split(",").includes(activeSort.key)) clearSort();
  }, [columnKeys, activeSort, clearSort]);
  const endDrag = () => { drag.current = null; setDropTarget(null); };
  const moveRow = (from: string, to: string) => {
    const next = moveGroupedRows(view.ordered, from, to);
    if (!next) return;
    // Preserve hidden/filtered identities when saving a visible reorder.
    layout.setRows([...next, ...completeOrder(items.map(i => i.symbol), layout.rows).filter(s => !next.includes(s))]);
    view.clearOrder();
  };

  const searchOptions = useMemo<WatchlistSearchOption[]>(() => view.ordered.filter(row => kindView === "all" || row.kind === kindView).map(row => {
    const profile = profilesBySymbol.get(row.kind === "stock" ? row.symbol : row.underlying ?? "");
    return {
      symbol: row.symbol,
      kind: row.kind,
      name: row.kind === "stock" ? (profile?.name || profile?.short_name || "") : `${row.underlying ?? ""}${row.issuer ? ` · ${row.issuer}` : ""}`,
      exchange: row.kind === "stock" ? profile?.exchange ?? null : "HOSE",
      underlying: row.underlying,
    };
  }), [view.ordered, profilesBySymbol, kindView]);
  const searchMatches = useMemo(() => matchingSymbols(searchOptions, symbolSearch), [searchOptions, symbolSearch]);
  const searched = useMemo(() => prioritizeWatchlist(view.ordered, searchMatches), [view.ordered, searchMatches]);
  // ALL / STOCK / CW is applied last, to the grouped display order only. Drag and Alt+↑/↓
  // still read `view.ordered`, so a reorder in one view never scrambles the other kind's
  // rows, and CW-only keeps each warrant in its underlying's group order.
  const displayRows = useMemo(
    () => kindView === "all" ? searched.rows : searched.rows.filter(row => row.kind === kindView),
    [searched.rows, kindView],
  );

  // Rendering 349 instruments used to create roughly 15k DOM/accessibility nodes. During
  // a busy SSI burst React then monopolised the browser main thread long enough to delay
  // both the clock timer and the WebSocket heartbeat. Keep the full ordered data model,
  // but only mount the rows around the scroll viewport.
  const tableScrollRef = useRef<HTMLDivElement>(null);
  const scrollFrame = useRef<number | null>(null);
  const [viewport, setViewport] = useState({ top: 0, height: 520 });
  const measureViewport = useCallback(() => {
    const node = tableScrollRef.current;
    if (!node) return;
    const next = { top: node.scrollTop, height: node.clientHeight || 520 };
    setViewport((current) => current.top === next.top && current.height === next.height ? current : next);
  }, []);
  const onTableScroll = useCallback(() => {
    if (scrollFrame.current !== null) return;
    scrollFrame.current = window.requestAnimationFrame(() => {
      scrollFrame.current = null;
      measureViewport();
    });
  }, [measureViewport]);
  useEffect(() => {
    measureViewport();
    const node = tableScrollRef.current;
    if (!node || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measureViewport);
    observer.observe(node);
    return () => {
      observer.disconnect();
      if (scrollFrame.current !== null) cancelAnimationFrame(scrollFrame.current);
    };
  }, [measureViewport]);
  useEffect(() => {
    if (!symbolSearch || !tableScrollRef.current) return;
    tableScrollRef.current.scrollTop = 0;
    measureViewport();
  }, [symbolSearch, measureViewport]);
  useEffect(() => {
    // A different set of rows starts at the top, as a new search does.
    if (!tableScrollRef.current) return;
    tableScrollRef.current.scrollTop = 0;
    measureViewport();
  }, [kindView, measureViewport]);

  const virtualized = displayRows.length > VIRTUALIZE_AFTER;
  const bodyTop = Math.max(0, viewport.top - (stockView ? BOARD_HEADER_HEIGHT : TABLE_HEADER_HEIGHT));
  const windowSize = Math.ceil(viewport.height / TABLE_ROW_HEIGHT) + VIRTUAL_OVERSCAN * 2;
  const unclampedStart = Math.max(0, Math.floor(bodyTop / TABLE_ROW_HEIGHT) - VIRTUAL_OVERSCAN);
  const startIndex = virtualized
    ? Math.min(unclampedStart, Math.max(0, displayRows.length - windowSize))
    : 0;
  const endIndex = virtualized ? Math.min(displayRows.length, startIndex + windowSize) : displayRows.length;
  const renderedRows = displayRows.slice(startIndex, endIndex);
  const spacerColSpan = columns.length + 2;

  // The symbol column follows the whole list (never just the mounted rows): the longest
  // symbol, +1ch CW indent, +2ch for each ◆ conflict / ◇ untracked mark (glyph + 5px).
  // The STOCK board sizes it from stocks alone; its hidden CWs would widen it for nothing.
  const symbolCh = Math.max(8, ...unifiedRows.filter(r => !stockView || r.kind === "stock").map((r) =>
    r.symbol.length + (r.kind === "cw" ? 1 : 0) + (r.conflicting ? 2 : 0) + (r.trackedRealtime ? 0 : 2)));
  const pad = stockView ? BOARD_CELL_PAD : CELL_PAD;
  const colWidth = (key: WatchlistColumnKey, label: string) =>
    columnWidth(label, key === "symbol" ? symbolCh : VALUE_CH[key], pad, stockView);
  const renderRow = (r: UnifiedRow) => {
    const selected = selectedSymbol === r.symbol;
    return (
      <tr
        title={(() => { const row = getRow(r.symbol); const p = row?.provenance?.quote; return p ? `${p.stale ? "STALE" : row?.displayState} · ${p.sessionDate ?? "Session unavailable"} · ${p.asOf ?? "Time unavailable"}` : "Data unavailable"; })()}
        key={r.symbol}
        data-symbol={r.symbol}
        className={`watchlist-row${r.kind === "cw" ? " watchlist-cw" : ""}${dropTarget === r.symbol ? " is-drop-target" : ""}${searched.highlighted.has(r.symbol) ? " is-search-match" : ""}${selected ? " is-selected" : ""}`}
        tabIndex={0}
        draggable
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
          background: selected || searched.highlighted.has(r.symbol) ? "var(--panel-3)" : r.kind === "cw" ? "var(--panel-2)" : "var(--bg)",
          borderBottom: ROW_BORDER,
        }}
      >
        <PinCell symbol={r.symbol} fill={view.pinFill(r.symbol)} onToggle={view.togglePin} />
        {columns.map(column => {
          const cell = watchlistCell(r, column.key);
          return column.key === "symbol" ? (
            <td key={column.key} className="watchlist-symbol-cell" title={r.trackedRealtime ? undefined : "Not tracked in the fixed realtime universe"} style={{ left: PIN_COL_WIDTH, padding: `0 ${pad}px`, paddingLeft: r.kind === "cw" ? `calc(${pad}px + 1ch)` : pad, color: cell.color, whiteSpace: "nowrap" }}>
              {r.symbol}
              {r.conflicting && <span title="Conflicting metadata — quant withheld" style={{ marginLeft: 5, color: "var(--down)" }}>◆</span>}
              {!r.trackedRealtime && <span className="untracked-realtime-mark" aria-label="Not tracked realtime" />}
            </td>
          ) : <RealtimeValue as="td" key={column.key} title={QUOTE_COLUMN_HINTS[column.key]}
            pulse={r.pulses?.[QUOTE_COLUMN_PULSE_FIELD[column.key] ?? ""]}
            tone={cell.tone}
            style={{ ...TD, padding: `0 ${pad}px`, color: cell.color }}>
            {r.kind === "stock" && ["ivBid", "ivTrade", "ivAsk", "strike", "ratio", "lastTradingDate", "dte", "issuer"].includes(column.key) ? null : cell.text}
          </RealtimeValue>;
        })}
        <DismissCell symbol={r.symbol} onDismiss={hiddenRows.hide} />
      </tr>
    );
  };

  return (
    <div className="page-shell">
      <MarketOverviewStrip />
      <div
        className="page-title-row"
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          marginBottom: 8,
          position: "relative",
        }}
      >
        <span className="heading" style={{ fontSize: 14, fontWeight: 700, letterSpacing: "0.02em" }}>
          Watchlist
        </span>
        <WatchlistSymbolSearch options={searchOptions} value={symbolSearch} onSubmit={setSymbolSearch} />
        <HiddenNote count={hiddenRows.count} onReset={hiddenRows.reset} />
        <div className="watchlist-view-controls">
          <InstrumentKindToggle value={kindView} onChange={setKindView} />
          <RegistryFilter
            underlyingOptions={underlyingOptions}
            issuerOptions={issuerOptions}
            value={filterState}
            onChange={setFilterState}
          />
        </div>
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
        <div className="watchlist-table-scroll" ref={tableScrollRef} onScroll={onTableScroll}>
        <table
          className="mono grid-lined watchlist-table"
          aria-rowcount={displayRows.length + 1}
          style={{ width: "100%", borderCollapse: "collapse", fontSize: 11.5 }}
        >
          <colgroup>
            <col style={{ width: PIN_COL_WIDTH }} />
            {columns.map(column => <col key={column.key} data-column={column.key} style={{ width: colWidth(column.key, column.label) }} />)}
            <col style={{ width: DISMISS_COL_WIDTH }} />
          </colgroup>
          <thead>
            <tr style={{ borderBottom: "1px solid var(--border-strong)" }}>
              <PinHeader />
              {columns.map((column, index) => (
                <th key={column.key} draggable tabIndex={0}
                  data-column={column.key}
                  className={dropTarget === column.key ? "is-drop-target" : undefined}
                  aria-sort={view.sortMark(column.key) === "▲" ? "ascending" : view.sortMark(column.key) === "▼" ? "descending" : "none"}
                  title={`${QUOTE_COLUMN_HINTS[column.key] ? `${QUOTE_COLUMN_HINTS[column.key]} · ` : ""}Click to sort · Drag to reorder · Alt + ←/→ to move`}
                  style={{ left: column.key === "symbol" ? PIN_COL_WIDTH : undefined, padding: `5px ${pad}px`, verticalAlign: stockView ? "bottom" : undefined, textAlign: column.key === "symbol" ? "left" : "right", color: "var(--t-92)", fontWeight: 500, cursor: "grab", userSelect: "none" }}
                  onClick={() => { if (!drag.current) view.toggleSort(column.key); }}
                  onDragStart={(e) => { drag.current = { type: "column", key: column.key }; e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", column.key); }}
                  onDragOver={(e) => { if (drag.current?.type === "column") { e.preventDefault(); e.dataTransfer.dropEffect = "move"; setDropTarget(column.key); } }}
                  onDrop={(e) => { e.preventDefault(); if (drag.current?.type === "column") moveColumn(drag.current.key, column.key); endDrag(); }}
                  onDragEnd={endDrag}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); view.toggleSort(column.key); }
                    if (e.altKey && (e.key === "ArrowLeft" || e.key === "ArrowRight")) {
                      e.preventDefault();
                      const to = columns[index + (e.key === "ArrowLeft" ? -1 : 1)];
                      if (to) moveColumn(column.key, to.key);
                    }
                  }}>
                  <span className="watchlist-column-label" style={{ flexDirection: column.key === "symbol" ? "row" : "row-reverse" }}>
                    <span>{labelLines(column.label, stockView).map((line, i) => <span key={i}>{i > 0 && <br />}{line}</span>)}</span>
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
            {virtualized && startIndex > 0 && (
              <tr aria-hidden="true" className="watchlist-virtual-spacer">
                <td colSpan={spacerColSpan} style={{ height: startIndex * TABLE_ROW_HEIGHT, padding: 0, border: 0 }} />
              </tr>
            )}
            {renderedRows.map(renderRow)}
            {displayRows.length === 0 && (
              <tr>
                <td colSpan={spacerColSpan} style={{ padding: "40px 8px", textAlign: "center", color: "var(--t-46)" }}>
                  {kindView === "stock" ? "No stocks match." : kindView === "cw" ? "No covered warrants match." : "No instruments match."}
                </td>
              </tr>
            )}
            {virtualized && endIndex < displayRows.length && (
              <tr aria-hidden="true" className="watchlist-virtual-spacer">
                <td colSpan={spacerColSpan} style={{ height: (displayRows.length - endIndex) * TABLE_ROW_HEIGHT, padding: 0, border: 0 }} />
              </tr>
            )}
          </tbody>
        </table>
        </div>
      )}
    </div>
  );
}
