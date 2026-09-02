import { useState } from "react";
import { useWatchlist } from "@/data/watchlist";
import { useActiveWarrants } from "@/data/query";
import { useInstrumentSpecs } from "@/data/instruments/use_instrument_specs";
import {
  EMPTY_FILTER,
  RegistryFilter,
  rowMatchesFilter,
} from "@/components/common/registry_filter";
import {
  DASH,
  DismissCell,
  PinCell,
  SortHeader,
  dteDisplay,
  dteNumber,
  fmtPrice,
  fmtRatio,
  useHiddenRows,
  useSortPin,
} from "@/components/common/grid_table";
import { EmptyState, Notice, UndoNotice } from "@/components/common/ui";

interface Props {
  onNavigateToDashboard?: () => void;
  selectedSymbol?: string | null;
  onSelectSymbol?: (symbol: string | null) => void;
  filter?: string;
}
export function ResearchUniverse({
  selectedSymbol,
  onSelectSymbol,
  filter = "",
}: Props) {
  const { isInWatchlist, addToWatchlist } = useWatchlist();
  const { getSpec } = useInstrumentSpecs();
  const [query, setQuery] = useState(filter);
  const [lifecycle, setLifecycle] = useState("ACTIVE");
  const [filters, setFilters] = useState(EMPTY_FILTER);
  const [note, setNote] = useState<string | null>(null);
  const [undo, setUndo] = useState<string | null>(null);
  const hidden = useHiddenRows();
  const { instruments, isLoading, isError, refetch } = useActiveWarrants({
    status: "ALL",
  });
  const all = instruments.map((cw) => {
    const spec = getSpec(cw.symbol);
    const maturity = spec?.maturityDate ?? cw.maturityDate;
    return {
      symbol: cw.symbol,
      issuer: spec?.issuer ?? cw.issuer,
      underlying: spec?.underlyingSymbol ?? cw.underlyingSymbol,
      strike: spec?.strikePrice ?? cw.strikePrice,
      ratio: spec?.exerciseRatio ?? cw.exerciseRatio,
      maturity,
      lastTradingDate: spec?.lastTradingDate ?? cw.lastTradingDate,
      dte: dteNumber(null, maturity),
      status:
        spec?.status ??
        cw.status ??
        ((dteNumber(null, maturity) ?? 0) < 0 ? "EXPIRED" : "ACTIVE"),
      verification:
        spec?.metadataVerification ?? cw.metadataVerification ?? "UNVERIFIED",
      tracked: isInWatchlist(cw.symbol),
    };
  });
  const term = query.trim().toUpperCase();
  const underlyingOptions = [
    ...new Set(all.map((c) => c.underlying).filter((v): v is string => !!v)),
  ].sort();
  const issuerOptions = [
    ...new Set(all.map((c) => c.issuer).filter((v): v is string => !!v)),
  ].sort();
  const rows = all.filter(
    (r) =>
      (lifecycle === "ALL" || r.status === lifecycle) &&
      (!term ||
        [r.symbol, r.underlying, r.issuer].some((v) =>
          v?.toUpperCase().includes(term),
        )) &&
      !hidden.isHidden(r.symbol) &&
      rowMatchesFilter(filters, r),
  );
  const grid = useSortPin(rows, {
    symbol: (r) => r.symbol,
    issuer: (r) => r.issuer,
    underlying: (r) => r.underlying,
    strike: (r) => r.strike,
    ratio: (r) => r.ratio,
    maturity: (r) => r.maturity,
    dte: (r) => r.dte,
  });
  const add = (symbol: string, underlying?: string | null) => {
    const res = addToWatchlist({
      symbol,
      instrumentType: underlying ? "CW" : "STOCK",
      underlyingSymbol: underlying,
    });
    setNote(
      res.success
        ? `${symbol} added to your watchlist`
        : (res.reason ?? "Could not add this instrument"),
    );
  };
  return (
    <section aria-label="Research registry">
      <div className="section-toolbar">
        <div>
          <h1 className="section-title">Research</h1>
          <p className="section-subtitle">
            Discover covered warrants and inspect their contract terms.
          </p>
        </div>
        <div className="actions">
          <input
            aria-label="Search registry"
            placeholder="Symbol, underlying or issuer…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <select
            aria-label="Lifecycle"
            value={lifecycle}
            onChange={(e) => setLifecycle(e.target.value)}
          >
            <option value="ACTIVE">Active warrants</option>
            <option value="ALL">All warrants</option>
            <option value="EXPIRED">Expired warrants</option>
          </select>
          <RegistryFilter
            underlyingOptions={underlyingOptions}
            issuerOptions={issuerOptions}
            value={filters}
            onChange={setFilters}
          />
        </div>
      </div>
      {note && (
        <Notice
          action={
            <button className="btn btn-link" onClick={() => setNote(null)}>
              Dismiss
            </button>
          }
        >
          {note}
        </Notice>
      )}
      <div className="registry-summary">
        <span>
          {rows.length} warrants
          {hidden.count ? ` · ${hidden.count} hidden` : ""}
        </span>
        {hidden.count > 0 && (
          <button className="btn btn-link" onClick={hidden.reset}>
            Show hidden
          </button>
        )}
        <span className="muted">
          Verification is independent of lifecycle and watchlist membership.
        </span>
      </div>
      {isLoading ? (
        <EmptyState title="Loading research registry…" />
      ) : isError ? (
        <EmptyState
          title="Could not load the registry"
          action={
            <button className="btn" onClick={() => void refetch()}>
              Retry
            </button>
          }
        />
      ) : rows.length === 0 ? (
        <EmptyState
          title="No instruments match"
          action={
            <button
              className="btn"
              onClick={() => {
                setQuery("");
                setFilters(EMPTY_FILTER);
                setLifecycle("ALL");
                hidden.reset();
              }}
            >
              Clear filters
            </button>
          }
        />
      ) : (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                {[
                  ["symbol", "SYMBOL"],
                  ["issuer", "ISSUER"],
                  ["underlying", "UNDERLYING"],
                  ["strike", "STRIKE"],
                  ["ratio", "RATIO"],
                  ["maturity", "MATURITY"],
                  ["dte", "DTE"],
                ].map(([key, label]) => (
                  <SortHeader
                    key={key}
                    label={label}
                    align={
                      ["symbol", "issuer", "underlying"].includes(key)
                        ? "left"
                        : "right"
                    }
                    mark={grid.sortMark(key)}
                    onClick={() => grid.toggleSort(key)}
                  />
                ))}
                <th>Lifecycle</th>
                <th>Verification</th>
                <th>Watchlist</th>
                <th aria-label="Pin" />
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {grid.ordered.map((r) => (
                <tr
                  key={r.symbol}
                  tabIndex={0}
                  className={r.symbol === selectedSymbol ? "is-selected" : ""}
                  aria-selected={r.symbol === selectedSymbol}
                  onClick={() => onSelectSymbol?.(r.symbol)}
                  onKeyDown={(e) => {
                    if (
                      e.target === e.currentTarget &&
                      (e.key === "Enter" || e.key === " ")
                    ) {
                      e.preventDefault();
                      onSelectSymbol?.(r.symbol);
                    }
                  }}
                >
                  <td className="symbol-cell">{r.symbol}</td>
                  <td style={{ textAlign: "left" }}>{r.issuer ?? DASH}</td>
                  <td style={{ textAlign: "left" }}>{r.underlying ?? DASH}</td>
                  <td>{fmtPrice(r.strike)}</td>
                  <td>{fmtRatio(r.ratio)}</td>
                  <td>{r.maturity || DASH}</td>
                  <td title="Calendar days to maturity, today in ICT">
                    {dteDisplay(null, r.maturity)}
                  </td>
                  <td>
                    <span className="badge">{r.status.toLowerCase()}</span>
                  </td>
                  <td>
                    <span
                      className={`badge ${r.verification === "VERIFIED_CURRENT" ? "badge-accent" : "badge-warning"}`}
                    >
                      {r.verification === "VERIFIED_CURRENT"
                        ? "Verified"
                        : r.verification === "CONFLICTING"
                          ? "Conflicting terms"
                          : r.verification.toLowerCase()}
                    </span>
                  </td>
                  <td>
                    {r.tracked ? (
                      <span className="badge badge-accent">Watching</span>
                    ) : (
                      <button
                        className="btn"
                        aria-label={`Add ${r.symbol} to watchlist`}
                        onClick={(e) => {
                          e.stopPropagation();
                          add(r.symbol, r.underlying);
                        }}
                      >
                        + Watch
                      </button>
                    )}
                  </td>
                  <PinCell
                    symbol={r.symbol}
                    fill={grid.pinFill(r.symbol)}
                    onToggle={grid.togglePin}
                  />
                  <DismissCell
                    symbol={r.symbol}
                    onDismiss={(s) => {
                      hidden.hide(s);
                      setUndo(s);
                    }}
                  />
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="underlying-list">
        <span className="muted">Underlying equities</span>
        {underlyingOptions
          .filter((s) => !term || s.includes(term))
          .map((symbol) => (
            <button
              className="btn"
              key={symbol}
              onClick={() => onSelectSymbol?.(symbol)}
            >
              {symbol}
            </button>
          ))}
      </div>
      {undo && (
        <UndoNotice
          text={`${undo} hidden from this view`}
          undo={() => {
            hidden.restore(undo);
            setUndo(null);
          }}
          dismiss={() => setUndo(null)}
        />
      )}
    </section>
  );
}
