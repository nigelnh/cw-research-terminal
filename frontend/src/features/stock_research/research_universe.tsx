import { useMemo, useState } from "react";
import { useWatchlist } from "@/data/watchlist";
import { useActiveWarrants } from "@/data/query";
import {
  EMPTY_FILTER,
  RegistryFilter,
  isFilterActive,
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
  SortHeader,
  dteDisplay,
  dteNumber,
  fmtPrice,
  fmtRatio,
  useHiddenRows,
  useSortPin,
  type SortFields,
} from "@/components/common/grid_table";

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

const FIELDS: SortFields<RegistryRow> = {
  symbol: (r) => r.symbol,
  issuer: (r) => r.issuer,
  und: (r) => r.underlying,
  strike: (r) => r.strike,
  ratio: (r) => r.ratio,
  maturity: (r) => r.maturity,
  dte: (r) => r.dte,
  status: (r) => (r.tracked ? "TRACKED" : "REFERENCE"),
};

const TD: React.CSSProperties = { padding: "0 8px", textAlign: "right" };

const STOCK_FIELDS: SortFields<{ symbol: string }> = { symbol: (r) => r.symbol };

export function ResearchUniverse({
  selectedSymbol = null,
  onSelectSymbol,
  filter = "",
}: ResearchUniverseProps) {
  const setSelected = onSelectSymbol ?? (() => {});
  const { isInWatchlist, addToWatchlist } = useWatchlist();
  const [filterState, setFilterState] = useState<FilterState>(EMPTY_FILTER);
  const hiddenRows = useHiddenRows();
  const stockHidden = useHiddenRows();
  const addCw = (r: RegistryRow) =>
    addToWatchlist({
      symbol: r.symbol,
      instrumentType: "CW",
      underlyingSymbol: r.underlying,
      issuer: r.issuer,
      strikePrice: r.strike,
      exerciseRatio: r.ratio,
      maturityDate: r.maturity,
      lastTradingDate: r.lastTradingDate,
    });

  const term = filter.trim().toUpperCase().replace(/^\//, "").trim();
  const browseAll = term.length > 0 || isFilterActive(filterState);

  const { instruments, isLoading, isError } = useActiveWarrants({
    status: browseAll ? "ALL" : "ACTIVE",
  });

  const activeCount = useMemo(
    () => instruments.filter((cw) => (cw as { status?: string }).status !== "EXPIRED").length,
    [instruments],
  );

  const rows: RegistryRow[] = useMemo(
    () =>
      instruments
        .map((cw) => {
          const lastTradingDate = cw.lastTradingDate ?? null;
          const maturity = cw.maturityDate ?? null;
          return {
            symbol: cw.symbol,
            issuer: cw.issuer ?? null,
            underlying: cw.underlyingSymbol ?? null,
            strike: cw.strikePrice ?? null,
            ratio: typeof cw.exerciseRatio === "number" ? cw.exerciseRatio : null,
            maturity,
            lastTradingDate,
            dte: dteNumber(lastTradingDate, maturity),
            dteText: dteDisplay(lastTradingDate, maturity),
            tracked: isInWatchlist(cw.symbol),
          };
        })
        .filter((r) => {
          if (term) {
            const hit =
              r.symbol.toUpperCase().includes(term) ||
              (r.underlying ?? "").toUpperCase().includes(term) ||
              (r.issuer ?? "").toUpperCase().includes(term);
            if (!hit) return false;
          }
          if (hiddenRows.isHidden(r.symbol)) return false;
          return rowMatchesFilter(filterState, {
            underlying: r.underlying,
            issuer: r.issuer,
            lastTradingDate: r.lastTradingDate,
          });
        }),
    [instruments, term, filterState, isInWatchlist, hiddenRows],
  );

  const underlyingOptions = useMemo(
    () => [...new Set(instruments.map((c) => c.underlyingSymbol).filter((v): v is string => !!v))].sort(),
    [instruments],
  );
  const issuerOptions = useMemo(
    () => [...new Set(instruments.map((c) => c.issuer).filter((v): v is string => !!v))].sort(),
    [instruments],
  );

  const grid = useSortPin(rows, FIELDS);

  // STOCKS column — the distinct underlyings backing the discovered CWs.
  const stockRows = useMemo(
    () =>
      underlyingOptions
        .filter((s) => !stockHidden.isHidden(s))
        .filter((s) => !term || s.toUpperCase().includes(term))
        .map((symbol) => ({ symbol })),
    [underlyingOptions, stockHidden, term],
  );
  const stockGrid = useSortPin(stockRows, STOCK_FIELDS);

  return (
    <div>
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 12,
          marginBottom: 3,
          position: "relative",
        }}
      >
        <span className="heading" style={{ fontSize: 14, fontWeight: 700, letterSpacing: "0.02em" }}>
          Registry
        </span>
        <span style={{ fontSize: 10.5, color: "var(--t-42)", fontStyle: "italic" }}>
          “{browseAll ? "browsing the full discovered registry" : "verified terms only"}”
        </span>
        <HiddenNote count={hiddenRows.count} onReset={hiddenRows.reset} />
        <RegistryFilter
          underlyingOptions={underlyingOptions}
          issuerOptions={issuerOptions}
          value={filterState}
          onChange={setFilterState}
        />
      </div>
      <p style={{ fontSize: 11, color: "var(--t-46)", marginBottom: 14 }}>
        {browseAll
          ? `${rows.length} match${rows.length === 1 ? "" : "es"}`
          : `${activeCount} verified · type in the header bar to filter across ~530 discovered`}
      </p>

      <div style={{ display: "flex", gap: 24, alignItems: "flex-start" }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 9.5, letterSpacing: "0.06em", color: "var(--t-46)", marginBottom: 6 }}>
            COVERED WARRANTS
          </div>
          <table className="mono grid-lined" style={{ width: "100%", borderCollapse: "collapse", fontSize: 11.5 }}>
            <thead>
              <tr style={{ borderBottom: "1px solid var(--border-strong)" }}>
                <PinHeader />
                <SortHeader label="SYMBOL" align="left" mark={grid.sortMark("symbol")} onClick={() => grid.toggleSort("symbol")} />
                <SortHeader label="ISSUER" align="left" mark={grid.sortMark("issuer")} onClick={() => grid.toggleSort("issuer")} />
                <SortHeader label="UNDERLYING" align="left" mark={grid.sortMark("und")} onClick={() => grid.toggleSort("und")} />
                <SortHeader label="STRIKE" mark={grid.sortMark("strike")} onClick={() => grid.toggleSort("strike")} />
                <SortHeader label="RATIO" mark={grid.sortMark("ratio")} onClick={() => grid.toggleSort("ratio")} />
                <SortHeader label="MATURITY" mark={grid.sortMark("maturity")} onClick={() => grid.toggleSort("maturity")} />
                <SortHeader label="DTE" mark={grid.sortMark("dte")} onClick={() => grid.toggleSort("dte")} />
                <SortHeader label="STATUS" mark={grid.sortMark("status")} onClick={() => grid.toggleSort("status")} />
                <th style={{ width: 20, padding: "5px 4px" }} aria-hidden />
                <DismissHeader />
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <tr>
                  <td colSpan={11} style={{ padding: "56px 0", textAlign: "center", fontSize: 12, color: "var(--t-46)" }}>
                    Loading research registry…
                  </td>
                </tr>
              ) : isError ? (
                <tr>
                  <td colSpan={11} style={{ padding: "56px 0", textAlign: "center", fontSize: 12, color: "var(--down)" }}>
                    Could not load the research registry. Retry shortly.
                  </td>
                </tr>
              ) : grid.ordered.length === 0 ? (
                <tr>
                  <td colSpan={11} style={{ padding: "56px 0", textAlign: "center", fontSize: 12, color: "var(--t-46)" }}>
                    No instruments match.
                  </td>
                </tr>
              ) : (
                grid.ordered.map((r) => {
                  const selected = selectedSymbol === r.symbol;
                  return (
                    <tr
                      key={r.symbol}
                      tabIndex={0}
                      onClick={() => setSelected(r.symbol)}
                      onKeyDown={(e) => e.key === "Enter" && setSelected(r.symbol)}
                      style={{
                        cursor: "pointer",
                        height: 27,
                        background: selected ? "var(--panel-3)" : "transparent",
                        borderBottom: "1px solid var(--border-row)",
                      }}
                    >
                      <PinCell symbol={r.symbol} fill={grid.pinFill(r.symbol)} onToggle={grid.togglePin} />
                      <td style={{ padding: "0 8px", color: "var(--accent)" }}>{r.symbol}</td>
                      <td style={{ padding: "0 8px", color: "var(--t-60)" }}>{r.issuer ?? DASH}</td>
                      <td style={{ padding: "0 8px", color: "var(--t-60)" }}>{r.underlying ?? DASH}</td>
                      <td style={{ ...TD, color: "var(--t-80)" }}>{fmtPrice(r.strike)}</td>
                      <td style={{ ...TD, color: "var(--t-50)" }}>{fmtRatio(r.ratio)}</td>
                      <td style={{ ...TD, color: "var(--t-50)" }}>{r.maturity ?? DASH}</td>
                      <td style={{ ...TD, color: "var(--t-46)" }}>{r.dteText}</td>
                      <td style={{ ...TD, color: r.tracked ? "var(--accent)" : "var(--t-46)" }}>
                        {r.tracked ? "TRACKED" : "REFERENCE"}
                      </td>
                      <AddCell symbol={r.symbol} tracked={r.tracked} onAdd={() => addCw(r)} />
                      <DismissCell symbol={r.symbol} onDismiss={hiddenRows.hide} />
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        <div style={{ width: 220, flexShrink: 0 }}>
          <div style={{ fontSize: 9.5, letterSpacing: "0.06em", color: "var(--t-46)", marginBottom: 6 }}>
            STOCKS
            <HiddenNote count={stockHidden.count} onReset={stockHidden.reset} />
          </div>
          <table className="mono grid-lined" style={{ width: "100%", borderCollapse: "collapse", fontSize: 11.5 }}>
            <thead>
              <tr style={{ borderBottom: "1px solid var(--border-strong)" }}>
                <PinHeader />
                <SortHeader label="SYMBOL" align="left" mark={stockGrid.sortMark("symbol")} onClick={() => stockGrid.toggleSort("symbol")} />
                <th style={{ width: 20, padding: "5px 4px" }} aria-hidden />
                <DismissHeader />
              </tr>
            </thead>
            <tbody>
              {stockGrid.ordered.length === 0 ? (
                <tr>
                  <td colSpan={4} style={{ padding: "24px 0", textAlign: "center", fontSize: 11, color: "var(--t-46)" }}>
                    —
                  </td>
                </tr>
              ) : (
                stockGrid.ordered.map((s) => {
                  const selected = selectedSymbol === s.symbol;
                  return (
                    <tr
                      key={s.symbol}
                      tabIndex={0}
                      onClick={() => setSelected(s.symbol)}
                      onKeyDown={(e) => e.key === "Enter" && setSelected(s.symbol)}
                      style={{
                        cursor: "pointer",
                        height: 27,
                        background: selected ? "var(--panel-3)" : "transparent",
                        borderBottom: "1px solid var(--border-row)",
                      }}
                    >
                      <PinCell symbol={s.symbol} fill={stockGrid.pinFill(s.symbol)} onToggle={stockGrid.togglePin} />
                      <td style={{ padding: "0 8px", color: "var(--accent)" }}>{s.symbol}</td>
                      <AddCell
                        symbol={s.symbol}
                        tracked={isInWatchlist(s.symbol)}
                        onAdd={() => addToWatchlist({ symbol: s.symbol, instrumentType: "STOCK" })}
                      />
                      <DismissCell symbol={s.symbol} onDismiss={stockHidden.hide} />
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
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
