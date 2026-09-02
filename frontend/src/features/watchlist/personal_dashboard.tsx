import { Fragment, useMemo, useState } from "react";
import type { WatchlistItem } from "@/domain/models";
import { useWatchlist } from "@/data/watchlist";
import { useResearchMarket } from "@/data/use_research_market";
import { useDashboardData } from "@/data/query/use_dashboard_data";
import { asOfLabel } from "@/domain/temporal";
import { useInstrumentSpecs } from "@/data/instruments/use_instrument_specs";
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
  PlainHeader,
  SortHeader,
  dteDisplay,
  dteNumber,
  fmtChg,
  fmtIV,
  fmtPrice,
  fmtRatio,
  fmtVol,
  priceColor,
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
  ref: number | null;
  ceiling: number | null;
  floor: number | null;
  chgPct: number | null;
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
  underlying: string | null;
  ref: number | null;
  bid: number | null;
  ask: number | null;
  last: number | null;
  chgPct: number | null;
  vol: number | null;
  ceiling: number | null;
  floor: number | null;
  strike: number | null;
  ratio: number | null;
  dteText: string;
  dte: number | null;
  ivBid: number | null;
  ivTrade: number | null;
  ivAsk: number | null;
  conflicting: boolean;
}

const UNIFIED_FIELDS: SortFields<UnifiedRow> = {
  symbol: (r) => r.symbol,
  ref: (r) => r.ref,
  bid: (r) => r.bid,
  ask: (r) => r.ask,
  trd: (r) => r.last,
  chg: (r) => r.chgPct,
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
  const { quotes, warrants, marketSessionActive } = useResearchMarket();
  const { getSpec } = useInstrumentSpecs();
  const [filterState, setFilterState] = useState<FilterState>(EMPTY_FILTER);
  const hiddenRows = useHiddenRows();

  const allSymbols = useMemo(() => items.map((i) => i.symbol), [items]);
  const { getRow, meta } = useDashboardData(allSymbols);

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

  const cwRows: CwRow[] = useMemo(
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
            ref: quote?.referencePrice ?? cw?.quote?.referencePrice ?? null,
            ceiling: quote?.ceilingPrice ?? cw?.quote?.ceilingPrice ?? null,
            floor: quote?.floorPrice ?? cw?.quote?.floorPrice ?? null,
            chgPct: typeof pctRaw === "number" ? pctRaw * 100 : null,
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
        .filter((r) => !hiddenRows.isHidden(r.symbol))
        .filter((r) =>
          rowMatchesFilter(filterState, {
            underlying: r.underlying,
            issuer: r.issuer,
            lastTradingDate: r.lastTradingDate,
          }),
        ),
    [items, getRow, quotes, warrants, getSpec, q, filterState, hiddenRows],
  );

  const underlyingOptions = useMemo(
    () => [...new Set(cwRows.map((r) => r.underlying).filter((v): v is string => !!v))].sort(),
    [cwRows],
  );
  const issuerOptions = useMemo(
    () => [...new Set(cwRows.map((r) => r.issuer).filter((v): v is string => !!v))].sort(),
    [cwRows],
  );

  const unifiedRows: UnifiedRow[] = useMemo(
    () => [
      ...stockRows.map((s): UnifiedRow => ({
        symbol: s.symbol,
        kind: "stock",
        underlying: null,
        ref: s.ref,
        bid: s.bid,
        ask: s.ask,
        last: s.last,
        chgPct: s.chgPct,
        vol: s.vol,
        ceiling: s.ceiling,
        floor: s.floor,
        strike: null,
        ratio: null,
        dteText: DASH,
        dte: null,
        ivBid: null,
        ivTrade: null,
        ivAsk: null,
        conflicting: false,
      })),
      ...cwRows.map((c): UnifiedRow => ({
        symbol: c.symbol,
        kind: "cw",
        underlying: c.underlying,
        ref: c.ref,
        bid: c.bid,
        ask: c.ask,
        last: c.last,
        chgPct: c.chgPct,
        vol: null,
        ceiling: c.ceiling,
        floor: c.floor,
        strike: c.strike,
        ratio: c.ratio,
        dteText: c.dteText,
        dte: c.dte,
        ivBid: c.ivBid,
        ivTrade: c.ivTrade,
        ivAsk: c.ivAsk,
        conflicting: c.conflicting,
      })),
    ],
    [stockRows, cwRows],
  );

  const view = useSortPin(unifiedRows, UNIFIED_FIELDS);

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

  const sessionNote =
    meta.marketSessionActive || marketSessionActive
      ? "live session"
      : meta.latestCompletedSession
      ? `market closed — showing ${
          asOfLabel({
            state: "LAST_SESSION",
            source: "EOD",
            sessionDate: meta.latestCompletedSession,
          }) || "last session"
        } close`
      : "market closed";

  const priceRef = (r: { ref: number | null; ceiling: number | null; floor: number | null }) => ({
    ref: r.ref,
    ceiling: r.ceiling,
    floor: r.floor,
  });

  const renderRow = (r: UnifiedRow, isChild: boolean) => {
    const chg = fmtChg(r.chgPct);
    const selected = selectedSymbol === r.symbol;
    const pr = priceRef(r);
    return (
      <tr
        key={r.symbol}
        onClick={() => setSelected(r.symbol)}
        style={{
          cursor: "pointer",
          height: 26,
          background: selected ? "var(--panel-3)" : "transparent",
          borderBottom: ROW_BORDER,
        }}
      >
        <PinCell symbol={r.symbol} fill={view.pinFill(r.symbol)} onToggle={view.togglePin} />
        <td
          style={{
            padding: "0 8px",
            paddingLeft: isChild ? 24 : 8,
            color: "var(--accent)",
            whiteSpace: "nowrap",
          }}
        >
          {isChild && <span style={{ color: "var(--t-46)" }}>↳ </span>}
          {r.symbol}
          {isChild && (
            <span style={{ marginLeft: 6, fontSize: 9, color: "var(--t-46)" }}>CW</span>
          )}
          {r.conflicting && (
            <span
              title="Conflicting metadata — quant withheld"
              style={{ marginLeft: 5, color: "var(--down)" }}
            >
              ◆
            </span>
          )}
        </td>
        <td style={{ ...TD, color: "var(--t-60)" }}>{fmtPrice(r.ref)}</td>
        <td style={{ ...TD, color: priceColor(r.bid, pr) }}>{fmtPrice(r.bid)}</td>
        <td style={{ ...TD, color: priceColor(r.ask, pr) }}>{fmtPrice(r.ask)}</td>
        <td style={{ ...TD, color: priceColor(r.last, pr) }}>{fmtPrice(r.last)}</td>
        <td style={{ ...TD, color: chg.color }}>
          {r.last !== null && r.ref !== null
            ? Math.abs(r.last - r.ref).toLocaleString("en-US", { maximumFractionDigits: 2 })
            : DASH}
        </td>
        <td style={{ ...TD, color: chg.color }}>{chg.text}</td>
        <td style={{ ...TD, color: "var(--t-50)" }}>{fmtVol(r.vol)}</td>
        <td style={{ ...TD, color: "var(--t-60)" }}>{fmtPrice(r.strike)}</td>
        <td style={{ ...TD, color: "var(--t-50)" }}>{fmtRatio(r.ratio)}</td>
        <td style={{ ...TD, color: "var(--t-46)" }}>{r.dteText}</td>
        <td style={{ ...TD, color: "var(--t-50)" }}>{fmtIV(r.ivBid)}</td>
        <td style={{ ...TD, color: "var(--t-85)" }}>{fmtIV(r.ivTrade)}</td>
        <td style={{ ...TD, color: "var(--t-50)" }}>{fmtIV(r.ivAsk)}</td>
        <DismissCell symbol={r.symbol} onDismiss={hiddenRows.hide} />
      </tr>
    );
  };

  return (
    <div>
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
        <span style={{ fontSize: 10.5, color: "var(--t-42)", fontStyle: "italic" }}>
          “{sessionNote}”
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
        <table
          className="mono grid-lined"
          style={{ width: "100%", borderCollapse: "collapse", fontSize: 11.5 }}
        >
          <thead>
            <tr style={{ borderBottom: "1px solid var(--border-strong)" }}>
              <PinHeader />
              <SortHeader label="SYMBOL" align="left" mark={view.sortMark("symbol")} onClick={() => view.toggleSort("symbol")} />
              <SortHeader label="REF" mark={view.sortMark("ref")} onClick={() => view.toggleSort("ref")} />
              <SortHeader label="BID" mark={view.sortMark("bid")} onClick={() => view.toggleSort("bid")} />
              <SortHeader label="ASK" mark={view.sortMark("ask")} onClick={() => view.toggleSort("ask")} />
              <SortHeader label="TRD" mark={view.sortMark("trd")} onClick={() => view.toggleSort("trd")} />
              <PlainHeader label="+/-" />
              <SortHeader label="CHG%" mark={view.sortMark("chg")} onClick={() => view.toggleSort("chg")} />
              <SortHeader label="VOLUME" mark={view.sortMark("vol")} onClick={() => view.toggleSort("vol")} />
              <SortHeader label="STRIKE" mark={view.sortMark("strike")} onClick={() => view.toggleSort("strike")} />
              <SortHeader label="RATIO" mark={view.sortMark("ratio")} onClick={() => view.toggleSort("ratio")} />
              <SortHeader label="DTE" mark={view.sortMark("dte")} onClick={() => view.toggleSort("dte")} />
              <SortHeader label="IV BID" mark={view.sortMark("ivBid")} onClick={() => view.toggleSort("ivBid")} />
              <SortHeader label="IV TRD" mark={view.sortMark("ivTrade")} onClick={() => view.toggleSort("ivTrade")} />
              <SortHeader label="IV ASK" mark={view.sortMark("ivAsk")} onClick={() => view.toggleSort("ivAsk")} />
              <DismissHeader />
            </tr>
          </thead>
          <tbody>
            {parents.map((p) => (
              <Fragment key={p.symbol}>
                {renderRow(p, false)}
                {childrenOf(p.symbol).map((c) => renderRow(c, true))}
              </Fragment>
            ))}
            {orphanCws.map((c) => renderRow(c, false))}
          </tbody>
        </table>
      )}
    </div>
  );
}
