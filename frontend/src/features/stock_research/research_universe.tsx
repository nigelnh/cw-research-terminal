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
  PinCell,
  PinHeader,
  SortHeader,
  dteDisplay,
  dteNumber,
  fmtPrice,
  fmtRatio,
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

export function ResearchUniverse({
  selectedSymbol = null,
  onSelectSymbol,
  filter = "",
}: ResearchUniverseProps) {
  const setSelected = onSelectSymbol ?? (() => {});
  const { isInWatchlist } = useWatchlist();
  const [filterState, setFilterState] = useState<FilterState>(EMPTY_FILTER);

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
          return rowMatchesFilter(filterState, {
            underlying: r.underlying,
            issuer: r.issuer,
            lastTradingDate: r.lastTradingDate,
          });
        }),
    [instruments, term, filterState, isInWatchlist],
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

      <table className="mono" style={{ width: "100%", borderCollapse: "collapse", fontSize: 11.5 }}>
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
          </tr>
        </thead>
        <tbody>
          {isLoading ? (
            <tr>
              <td colSpan={9} style={{ padding: "56px 0", textAlign: "center", fontSize: 12, color: "var(--t-46)" }}>
                Loading research registry…
              </td>
            </tr>
          ) : isError ? (
            <tr>
              <td colSpan={9} style={{ padding: "56px 0", textAlign: "center", fontSize: 12, color: "var(--down)" }}>
                Could not load the research registry. Retry shortly.
              </td>
            </tr>
          ) : grid.ordered.length === 0 ? (
            <tr>
              <td colSpan={9} style={{ padding: "56px 0", textAlign: "center", fontSize: 12, color: "var(--t-46)" }}>
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
                </tr>
              );
            })
          )}
        </tbody>
      </table>
    </div>
  );
}
