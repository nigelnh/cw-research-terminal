import { useMemo, useState } from "react";
import { useWatchlist } from "@/data/watchlist";
import { useActiveWarrants } from "@/data/query";
import { EMPTY_FILTER, RegistryFilter, isFilterActive, rowMatchesFilter, type FilterState } from "@/components/common/registry_filter";
import { DASH, DismissCell, HiddenNote, dteDisplay, dteNumber, fmtPrice, fmtRatio, useHiddenRows } from "@/components/common/grid_table";
import { MarketOverviewStrip } from "@/features/watchlist/market_overview_strip";
import { useStockProfiles } from "@/data/query/use_stock_profiles";
import { WatchlistSymbolSearch, matchingSymbols, type WatchlistSearchOption } from "@/features/watchlist/watchlist_symbol_search";
import { ResearchTable, type ResearchColumn } from "./research_table";

interface ResearchUniverseProps {
  onNavigateToDashboard?: () => void;
  selectedSymbol?: string | null;
  onSelectSymbol?: (symbol: string | null) => void;
  filter?: string;
}
interface RegistryRow {
  symbol: string;
  issuer: string | null;
  underlying: string | null;
  strike: number | null;
  ratio: number | null;
  maturity: string | null;
  lastTradingDate: string | null;
  dte: number | null;
  dteText: string;
  tracked: boolean;
}
interface StockRegistryRow { symbol: string; exchange: string | null }

const CW_COLUMNS: ResearchColumn<RegistryRow>[] = [
  { key: "symbol", label: "SYMBOL", align: "left", value: r => r.symbol, render: r => r.symbol, color: "var(--t-92)" },
  { key: "issuer", label: "ISSUER", align: "left", value: r => r.issuer, render: r => r.issuer ?? DASH },
  { key: "und", label: "UNDERLYING", align: "left", value: r => r.underlying, render: r => r.underlying ?? DASH },
  { key: "strike", label: "STRIKE", value: r => r.strike, render: r => fmtPrice(r.strike), color: "var(--t-80)" },
  { key: "ratio", label: "RATIO", value: r => r.ratio, render: r => fmtRatio(r.ratio), color: "var(--t-50)" },
  { key: "lastTradingDate", label: "LAST_TRD_DATE", value: r => r.lastTradingDate, render: r => r.lastTradingDate ?? DASH, color: "var(--t-50)" },
  { key: "maturity", label: "MATURITY", value: r => r.maturity, render: r => r.maturity ?? DASH, color: "var(--t-50)" },
  { key: "dte", label: "DTE", value: r => r.dte, render: r => r.dteText, color: "var(--t-46)" },
  { key: "status", label: "STATUS", value: r => r.tracked ? "TRACKED" : "REFERENCE", render: r => r.tracked ? "TRACKED" : "REFERENCE", color: r => r.tracked ? "var(--accent)" : "var(--t-46)" },
];
const STOCK_COLUMNS: ResearchColumn<StockRegistryRow>[] = [
  { key: "symbol", label: "SYMBOL", align: "left", value: r => r.symbol, render: r => r.symbol, color: "var(--accent)" },
  { key: "exchange", label: "EXCHANGE", align: "left", value: r => r.exchange, render: r => r.exchange ?? DASH },
];

export function ResearchUniverse({ selectedSymbol = null, onSelectSymbol, filter = "" }: ResearchUniverseProps) {
  const setSelected = onSelectSymbol ?? (() => {});
  const { isInWatchlist, addToWatchlist } = useWatchlist();
  const [filterState, setFilterState] = useState<FilterState>(EMPTY_FILTER);
  const [symbolSearch, setSymbolSearch] = useState("");
  const hiddenRows = useHiddenRows();
  const stockHidden = useHiddenRows();
  const term = filter.trim().toUpperCase().replace(/^\//, "").trim();
  const browseAll = term.length > 0 || symbolSearch.length > 0 || isFilterActive(filterState);
  const active = useActiveWarrants({ status: "ACTIVE" });
  // Metadata only: suggestions can find discovered symbols without adding quote subscriptions.
  const discovered = useActiveWarrants({ status: "ALL" });
  const { instruments, isLoading, isError } = browseAll ? discovered : active;
  const searchable = discovered.instruments.length ? discovered.instruments : active.instruments;
  const underlyingOptions = useMemo(() => [...new Set(searchable.map(c => c.underlyingSymbol).filter((v): v is string => !!v))].sort(), [searchable]);
  const issuerOptions = useMemo(() => [...new Set(searchable.map(c => c.issuer).filter((v): v is string => !!v))].sort(), [searchable]);
  const { profiles } = useStockProfiles(underlyingOptions);
  const profilesBySymbol = useMemo(() => new Map(profiles.map(profile => [profile.symbol, profile])), [profiles]);
  const searchOptions = useMemo<WatchlistSearchOption[]>(() => [
    ...underlyingOptions.map(symbol => ({ symbol, kind: "stock" as const, name: profilesBySymbol.get(symbol)?.name || profilesBySymbol.get(symbol)?.short_name || "", exchange: profilesBySymbol.get(symbol)?.exchange ?? null, underlying: null })),
    ...searchable.map(cw => ({ symbol: cw.symbol, kind: "cw" as const, name: `${cw.underlyingSymbol ?? ""}${cw.issuer ? ` · ${cw.issuer}` : ""}`, exchange: "HOSE", underlying: cw.underlyingSymbol ?? null })),
  ], [underlyingOptions, profilesBySymbol, searchable]);
  const matches = useMemo(() => matchingSymbols(searchOptions, symbolSearch), [searchOptions, symbolSearch]);
  const rows = useMemo<RegistryRow[]>(() => instruments.map(cw => {
    const lastTradingDate = cw.lastTradingDate ?? null;
    const maturity = cw.maturityDate ?? null;
    return {
      symbol: cw.symbol, issuer: cw.issuer ?? null, underlying: cw.underlyingSymbol ?? null,
      strike: cw.strikePrice ?? null, ratio: typeof cw.exerciseRatio === "number" ? cw.exerciseRatio : null,
      maturity, lastTradingDate, dte: dteNumber(lastTradingDate, maturity), dteText: dteDisplay(lastTradingDate, maturity), tracked: isInWatchlist(cw.symbol),
    };
  }).filter(row => {
    if (term && ![row.symbol, row.underlying, row.issuer].some(value => value?.toUpperCase().includes(term))) return false;
    return !hiddenRows.isHidden(row.symbol) && rowMatchesFilter(filterState, row);
  }), [instruments, term, filterState, hiddenRows, isInWatchlist]);
  const stockRows = useMemo(() => [...new Set(instruments.map(cw => cw.underlyingSymbol).filter((s): s is string => !!s))].sort()
    .filter(symbol => !stockHidden.isHidden(symbol))
    .filter(symbol => !term || symbol.includes(term) || profilesBySymbol.get(symbol)?.name?.toUpperCase().includes(term))
    .map(symbol => ({ symbol, exchange: profilesBySymbol.get(symbol)?.exchange ?? null })), [instruments, stockHidden, term, profilesBySymbol]);
  const addCw = (row: RegistryRow) => addToWatchlist({
    symbol: row.symbol, instrumentType: "CW", underlyingSymbol: row.underlying, issuer: row.issuer,
    strikePrice: row.strike, exerciseRatio: row.ratio, maturityDate: row.maturity, lastTradingDate: row.lastTradingDate,
  });

  return <div>
    <MarketOverviewStrip />
    <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8, position: "relative" }}>
      <span className="heading" style={{ fontSize: 14, fontWeight: 700, letterSpacing: "0.02em" }}>Registry</span>
      <WatchlistSymbolSearch scope="research" options={searchOptions} value={symbolSearch} onSubmit={setSymbolSearch} />
      <HiddenNote count={hiddenRows.count} onReset={hiddenRows.reset} />
      <RegistryFilter underlyingOptions={underlyingOptions} issuerOptions={issuerOptions} value={filterState} onChange={setFilterState} />
    </div>
    <div className="research-registry-grid">
      <div className="research-registry-panel">
        <div style={{ fontSize: 9.5, letterSpacing: "0.06em", color: "var(--t-46)", marginBottom: 6 }}>COVERED WARRANTS</div>
        <ResearchTable id="warrants" label="Covered warrants" rows={rows} columns={CW_COLUMNS} selectedSymbol={selectedSymbol}
          matches={matches} onSelect={setSelected} isLoading={isLoading} isError={isError}
          actions={row => <><AddCell symbol={row.symbol} tracked={row.tracked} onAdd={() => addCw(row)} /><DismissCell symbol={row.symbol} onDismiss={hiddenRows.hide} /></>} />
      </div>
      <div className="research-stock-panel">
        <div style={{ fontSize: 9.5, letterSpacing: "0.06em", color: "var(--t-46)", marginBottom: 6 }}>
          STOCKS <HiddenNote count={stockHidden.count} onReset={stockHidden.reset} />
        </div>
        <ResearchTable id="stocks" label="Stocks" rows={stockRows} columns={STOCK_COLUMNS} selectedSymbol={selectedSymbol}
          matches={matches} onSelect={setSelected} isLoading={isLoading} isError={isError}
          actions={row => <><AddCell symbol={row.symbol} tracked={isInWatchlist(row.symbol)} onAdd={() => addToWatchlist({ symbol: row.symbol, instrumentType: "STOCK" })} /><DismissCell symbol={row.symbol} onDismiss={stockHidden.hide} /></>} />
      </div>
    </div>
  </div>;
}

/** Trailing "+" cell — adds the row's symbol to the watchlist. */
function AddCell({
  symbol,
  tracked,
  onAdd,
}: {
  symbol: string;
  tracked: boolean;
  onAdd: () => void;
}) {
  return (
    <td style={{ padding: "0 6px", textAlign: "center", width: 20 }}>
      <button
        type="button"
        disabled={tracked}
        onClick={(e) => {
          e.stopPropagation();
          onAdd();
        }}
        title={tracked ? `${symbol} is on your watchlist` : `Add ${symbol} to watchlist`}
        aria-label={tracked ? `${symbol} already on watchlist` : `Add ${symbol} to watchlist`}
        className="focus-ring"
        style={{
          background: "none",
          border: "none",
          cursor: tracked ? "default" : "pointer",
          padding: 2,
          lineHeight: 1,
          fontSize: 12,
          color: tracked ? "var(--t-40)" : "var(--accent)",
        }}
      >
        +
      </button>
    </td>
  );
}
