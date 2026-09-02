import { Fragment, useMemo, useRef, useState } from "react";
import { useWatchlist } from "@/data/watchlist";
import { useResearchMarket } from "@/data/use_research_market";
import { useDashboardData } from "@/data/query/use_dashboard_data";
import { asOfLabel, formatAsOf } from "@/domain/temporal";
import { useInstrumentSpecs } from "@/data/instruments/use_instrument_specs";
import {
  EMPTY_FILTER,
  RegistryFilter,
  isFilterActive,
  rowMatchesFilter,
} from "@/components/common/registry_filter";
import {
  DASH,
  DismissCell,
  PinCell,
  SortHeader,
  dteDisplay,
  dteNumber,
  fmtChg,
  fmtIV,
  fmtPrice,
  fmtSigned,
  fmtRatio,
  fmtVol,
  priceColor,
  useHiddenRows,
  useSortPin,
  type SortFields,
} from "@/components/common/grid_table";
import {
  EmptyState,
  Notice,
  UndoNotice,
  useStoredState,
} from "@/components/common/ui";

interface Props {
  onNavigateToUniverse?: () => void;
  selectedSymbol?: string | null;
  onSelectSymbol?: (symbol: string | null) => void;
  filter?: string;
}
interface Row {
  symbol: string;
  kind: "STOCK" | "CW" | "INDEX";
  underlying: string | null;
  issuer: string | null;
  ref: number | null;
  bid: number | null;
  ask: number | null;
  last: number | null;
  change: number | null;
  pct: number | null;
  volume: number | null;
  ceiling: number | null;
  floor: number | null;
  strike: number | null;
  ratio: number | null;
  maturity: string | null;
  lastTradingDate: string | null;
  dte: number | null;
  ivBid: number | null;
  ivTrade: number | null;
  ivAsk: number | null;
  conflicting: boolean;
  state: string;
  asOf: string | null;
}
const fields: SortFields<Row> = {
  symbol: (r) => r.symbol,
  ref: (r) => r.ref,
  bid: (r) => r.bid,
  ask: (r) => r.ask,
  last: (r) => r.last,
  change: (r) => r.change,
  pct: (r) => r.pct,
  volume: (r) => r.volume,
  strike: (r) => r.strike,
  ratio: (r) => r.ratio,
  dte: (r) => r.dte,
  ivBid: (r) => r.ivBid,
  ivTrade: (r) => r.ivTrade,
  ivAsk: (r) => r.ivAsk,
};
const FULL = [
  ["symbol", "SYMBOL"],
  ["ref", "REF"],
  ["bid", "BID"],
  ["ask", "ASK"],
  ["last", "LAST"],
  ["change", "+/-"],
  ["pct", "CHG%"],
  ["volume", "VOLUME"],
  ["strike", "STRIKE"],
  ["ratio", "RATIO"],
  ["dte", "DTE"],
  ["ivBid", "IV BID"],
  ["ivTrade", "IV TRADE"],
  ["ivAsk", "IV ASK"],
];
const BASIC = FULL.filter(([key]) =>
  ["symbol", "last", "change", "pct", "volume", "dte", "ivTrade"].includes(key),
);

export function PersonalDashboard({
  onNavigateToUniverse,
  selectedSymbol = null,
  onSelectSymbol,
  filter = "",
}: Props) {
  const { items, removeFromWatchlist, addToWatchlist } = useWatchlist();
  const addCurrent = useRef(addToWatchlist);
  addCurrent.current = addToWatchlist;
  const { quotes, warrants, marketSessionActive } = useResearchMarket();
  const { getSpec } = useInstrumentSpecs();
  const [query, setQuery] = useState(filter);
  const [filters, setFilters] = useState(EMPTY_FILTER);
  const hidden = useHiddenRows();
  const [full, setFull] = useStoredState("cw:watchlist:full-columns", false);
  const [undo, setUndo] = useState<{ text: string; run: () => void } | null>(
    null,
  );
  const symbols = useMemo(() => items.map((i) => i.symbol), [items]);
  const { getRow, meta, isLoading, isError, refetch } =
    useDashboardData(symbols);
  const rows: Row[] = items.map((item) => {
    const fallback = getRow(item.symbol);
    const q = fallback?.quote ?? quotes.get(item.symbol);
    const cw = warrants.get(item.symbol);
    const spec = getSpec(item.symbol);
    const kind = item.instrumentType ?? q?.instrumentType ?? "STOCK";
    const analytics =
      fallback?.displayState === "LIVE" ? cw : fallback?.analytics;
    const quantAllowed =
      spec?.metadataVerification !== "CONFLICTING" &&
      fallback?.analytics?.isAvailable !== false &&
      (fallback?.displayState !== "LIVE" || cw?.quantAvailable !== false);
    const n = (value: unknown) =>
      typeof value === "number" && Number.isFinite(value) ? value : null;
    const last = n(q?.lastPrice);
    const ref = n(q?.referencePrice);
    return {
      symbol: item.symbol,
      kind,
      underlying: spec?.underlyingSymbol ?? item.underlyingSymbol ?? null,
      issuer: spec?.issuer ?? null,
      ref,
      bid: n(q?.bidPrice),
      ask: n(q?.askPrice),
      last,
      change: last !== null && ref !== null ? last - ref : null,
      pct:
        typeof q?.priceChangePercent === "number"
          ? q.priceChangePercent * 100
          : null,
      volume: n(q?.totalVolume),
      ceiling: n(q?.ceilingPrice),
      floor: n(q?.floorPrice),
      strike: n(spec?.strikePrice),
      ratio: n(spec?.exerciseRatio),
      maturity: spec?.maturityDate ?? null,
      lastTradingDate: spec?.lastTradingDate ?? null,
      dte: kind === "CW" ? dteNumber(null, spec?.maturityDate) : null,
      ivBid: quantAllowed ? n(analytics?.ivBid) : null,
      ivTrade: quantAllowed ? n(analytics?.ivTrade) : null,
      ivAsk: quantAllowed ? n(analytics?.ivAsk) : null,
      conflicting: spec?.metadataVerification === "CONFLICTING",
      state: fallback?.displayState ?? "UNAVAILABLE",
      asOf:
        fallback?.provenance.quote.asOf ??
        fallback?.provenance.quote.sessionDate ??
        null,
    };
  });
  // Options come from the entire watchlist, never the already-filtered rows.
  const underlyingOptions = [
    ...new Set(rows.map((r) => r.underlying).filter((s): s is string => !!s)),
  ].sort();
  const issuerOptions = [
    ...new Set(rows.map((r) => r.issuer).filter((s): s is string => !!s)),
  ].sort();
  const term = query.trim().toUpperCase();
  const match = (r: Row) =>
    !term ||
    [r.symbol, r.underlying, r.issuer].some((s) =>
      s?.toUpperCase().includes(term),
    );
  const children = rows.filter(
    (r) =>
      r.kind === "CW" &&
      match(r) &&
      !hidden.isHidden(r.symbol) &&
      rowMatchesFilter(filters, r),
  );
  const parents = rows.filter(
    (r) =>
      r.kind !== "CW" &&
      !hidden.isHidden(r.symbol) &&
      (isFilterActive(filters)
        ? children.some((c) => c.underlying === r.symbol)
        : match(r) || children.some((c) => c.underlying === r.symbol)),
  );
  const view = useSortPin([...parents, ...children], fields);
  const orderedParents = view.ordered.filter((r) => r.kind !== "CW");
  const childrenOf = (symbol: string) =>
    view.ordered.filter((r) => r.kind === "CW" && r.underlying === symbol);
  const orphans = view.ordered.filter(
    (r) => r.kind === "CW" && !parents.some((p) => p.symbol === r.underlying),
  );
  const columns = full ? FULL : BASIC;
  const clear = () => {
    setQuery("");
    setFilters(EMPTY_FILTER);
    hidden.reset();
  };
  const hide = (symbol: string) => {
    hidden.hide(symbol);
    setUndo({
      text: `${symbol} hidden from this view`,
      run: () => hidden.restore(symbol),
    });
  };
  const remove = (symbol: string) => {
    const item = items.find((i) => i.symbol === symbol);
    if (!item) return;
    removeFromWatchlist(symbol);
    setUndo({
      text: `${symbol} removed from watchlist`,
      run: () => {
        const result = addCurrent.current(item);
        if (!result.success)
          setUndo({
            text: result.reason ?? "Could not restore this instrument",
            run: () => {},
          });
      },
    });
  };
  const cell = (r: Row, key: string) => {
    const change = fmtChg(r.pct);
    if (["ref", "bid", "ask", "last"].includes(key)) {
      const v = r[key as "ref" | "bid" | "ask" | "last"];
      return (
        <span
          style={{
            color:
              key === "ref"
                ? "var(--t-70)"
                : priceColor(v, {
                    ref: r.ref,
                    ceiling: r.ceiling,
                    floor: r.floor,
                  }),
          }}
          title={
            key === "last"
              ? `${r.state.replace(/_/g, " ")} · ${formatAsOf(r.asOf)}`
              : undefined
          }
        >
          {fmtPrice(v, r.kind)}
        </span>
      );
    }
    if (key === "change")
      return (
        <span style={{ color: change.color }}>
          {fmtSigned(r.change, r.kind)}
        </span>
      );
    if (key === "pct")
      return <span style={{ color: change.color }}>{change.text}</span>;
    if (key === "volume") return fmtVol(r.volume);
    if (key === "strike") return fmtPrice(r.strike);
    if (key === "ratio") return fmtRatio(r.ratio);
    if (key === "dte")
      return r.kind === "CW" ? (
        <span title="Calendar days to maturity, today in ICT">
          {dteDisplay(null, r.maturity)}
        </span>
      ) : (
        DASH
      );
    return fmtIV(r[key as "ivBid" | "ivTrade" | "ivAsk"]);
  };
  const render = (r: Row, child: boolean) => (
    <tr
      key={r.symbol}
      tabIndex={0}
      aria-selected={selectedSymbol === r.symbol}
      className={selectedSymbol === r.symbol ? "is-selected" : ""}
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
      {columns.map(([key]) =>
        key === "symbol" ? (
          <td
            key={key}
            className={`symbol-cell ${child ? "symbol-child" : ""}`}
          >
            {child && <span className="child-mark">↳ </span>}
            {r.symbol}
            {r.kind === "CW" && <small className="kind-mark">CW</small>}
            {r.conflicting && (
              <span
                className="badge badge-warning"
                title="Conflicting metadata — quant withheld"
              >
                !
              </span>
            )}
          </td>
        ) : (
          <td key={key}>{cell(r, key)}</td>
        ),
      )}
      <PinCell
        symbol={r.symbol}
        fill={view.pinFill(r.symbol)}
        onToggle={view.togglePin}
      />
      <DismissCell symbol={r.symbol} onDismiss={hide} onRemove={remove} />
    </tr>
  );
  return (
    <section aria-label="Watchlist">
      <div className="section-toolbar">
        <div>
          <h1 className="section-title">Watchlist</h1>
          <p className="section-subtitle">
            <span
              className={`data-status ${marketSessionActive ? "live" : ""}`}
            >
              {marketSessionActive
                ? "Market session open"
                : `Last session${meta.latestCompletedSession ? ` · ${asOfLabel({ state: "LAST_SESSION", source: "EOD", sessionDate: meta.latestCompletedSession })}` : " unavailable"}`}
            </span>
            <span className="status-explanation">
              Prices in VND · indices in points
            </span>
          </p>
        </div>
        <div className="actions">
          <input
            aria-label="Filter watchlist"
            placeholder="Filter watchlist…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <div className="segmented" aria-label="Visible columns">
            <button
              className={`btn ${!full ? "is-active" : ""}`}
              onClick={() => setFull(false)}
              aria-pressed={!full}
            >
              Basic
            </button>
            <button
              className={`btn ${full ? "is-active" : ""}`}
              onClick={() => setFull(true)}
              aria-pressed={full}
            >
              Full
            </button>
          </div>
          <RegistryFilter
            underlyingOptions={underlyingOptions}
            issuerOptions={issuerOptions}
            value={filters}
            onChange={setFilters}
          />
        </div>
      </div>
      {isError && (
        <Notice
          error
          action={
            <button className="btn" onClick={() => void refetch()}>
              Retry
            </button>
          }
        >
          Market data could not be refreshed. Previously available values retain
          their timestamps.
        </Notice>
      )}
      {isLoading && <Notice>Loading watchlist data…</Notice>}
      {hidden.count > 0 && (
        <Notice
          action={
            <button className="btn btn-link" onClick={hidden.reset}>
              Show all
            </button>
          }
        >
          {hidden.count} hidden from this view
        </Notice>
      )}
      {items.length === 0 ? (
        <EmptyState
          title="Build your watchlist"
          action={
            <button className="btn btn-primary" onClick={onNavigateToUniverse}>
              Browse research
            </button>
          }
        >
          Track a covered warrant or its underlying to compare prices and
          explore analytics.
        </EmptyState>
      ) : view.ordered.length === 0 ? (
        <EmptyState
          title="No instruments match"
          action={
            <button className="btn" onClick={clear}>
              Clear filters
            </button>
          }
        >
          Try another symbol or clear your current filters.
        </EmptyState>
      ) : (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              {full && (
                <tr className="group-head">
                  <th>Instrument</th>
                  <th colSpan={7}>Market</th>
                  <th colSpan={3}>Contract</th>
                  <th colSpan={3}>Volatility</th>
                  <th colSpan={2}>Actions</th>
                </tr>
              )}
              <tr>
                {columns.map(([key, label]) => (
                  <SortHeader
                    key={key}
                    label={label}
                    align={key === "symbol" ? "left" : "right"}
                    mark={view.sortMark(key)}
                    onClick={() => view.toggleSort(key)}
                  />
                ))}
                <th aria-label="Pin" />
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {orderedParents.map((p) => (
                <Fragment key={p.symbol}>
                  {render(p, false)}
                  {childrenOf(p.symbol).map((c) => render(c, true))}
                </Fragment>
              ))}
              {orphans.map((c) => render(c, false))}
            </tbody>
          </table>
        </div>
      )}
      {!selectedSymbol && items.length > 0 && (
        <div className="workspace-hint">
          <span>
            Select an instrument to inspect its chart, contract and research.
          </span>
          <button className="btn btn-link" onClick={onNavigateToUniverse}>
            Browse research →
          </button>
          <button
            className="btn btn-link"
            onClick={() => window.dispatchEvent(new Event("cw:open-assistant"))}
          >
            Ask the assistant
          </button>
        </div>
      )}
      {undo && (
        <UndoNotice
          text={undo.text}
          undo={() => {
            const run = undo.run;
            setUndo(null);
            run();
          }}
          dismiss={() => setUndo(null)}
        />
      )}
    </section>
  );
}
