import { useMemo, useState } from "react";
import type { WatchlistItem } from "@/domain/models";
import { useWatchlist } from "@/data/watchlist";
import { useResearchMarket } from "@/data/use_research_market";
import { useDashboardData } from "@/data/query/use_dashboard_data";
import { asOfLabel } from "@/domain/temporal";
import { useInstrumentSpecs } from "@/data/instruments/use_instrument_specs";
import { MarketOverviewStrip } from "@/components/common/market_overview_strip";
import {
  EMPTY_FILTER,
  RegistryFilter,
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
  fmtChg,
  fmtIV,
  fmtPrice,
  fmtRatio,
  fmtVol,
  priceColor,
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
  forBuy: number | null;
  forSell: number | null;
  room: number | null;
}

interface CwRow {
  symbol: string;
  underlying: string | null;
  issuer: string | null;
  undPrice: number | null;
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

const STOCK_FIELDS: SortFields<StockRow> = {
  symbol: (r) => r.symbol,
  ref: (r) => r.ref,
  bid: (r) => r.bid,
  ask: (r) => r.ask,
  trd: (r) => r.last,
  chg: (r) => r.chgPct,
  vol: (r) => r.vol,
  forBuy: (r) => r.forBuy,
  forSell: (r) => r.forSell,
  room: (r) => r.room,
};

const CW_FIELDS: SortFields<CwRow> = {
  symbol: (r) => r.symbol,
  und: (r) => r.underlying,
  undPrice: (r) => r.undPrice,
  bid: (r) => r.bid,
  ask: (r) => r.ask,
  trd: (r) => r.last,
  chg: (r) => r.chgPct,
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
  const { items, plan } = useWatchlist();
  const { quotes, warrants, marketSessionActive } = useResearchMarket();
  const { getSpec } = useInstrumentSpecs();
  const [filterState, setFilterState] = useState<FilterState>(EMPTY_FILTER);

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
            forBuy: quote?.foreignBuy ?? null,
            forSell: quote?.foreignSell ?? null,
            room: quote?.foreignRoom ?? null,
          };
        })
        .filter((r) => textMatch(r.symbol)),
    [items, getRow, quotes, q],
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
          const undPrice =
            cw?.underlyingPrice ??
            (underlying
              ? getRow(underlying)?.quote?.lastPrice ?? quotes.get(underlying)?.lastPrice ?? null
              : null);
          const last = quote?.lastPrice ?? cw?.quote?.lastPrice ?? null;
          const pctRaw = quote?.priceChangePercent ?? cw?.quote?.priceChangePercent ?? null;
          const lastTradingDate = spec?.lastTradingDate ?? null;
          const maturityDate = spec?.maturityDate ?? null;
          return {
            symbol: item.symbol,
            underlying,
            issuer: spec?.issuer ?? null,
            undPrice,
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
        .filter((r) =>
          rowMatchesFilter(filterState, {
            underlying: r.underlying,
            issuer: r.issuer,
            lastTradingDate: r.lastTradingDate,
          }),
        ),
    [items, getRow, quotes, warrants, getSpec, q, filterState],
  );

  const underlyingOptions = useMemo(
    () => [...new Set(cwRows.map((r) => r.underlying).filter((v): v is string => !!v))].sort(),
    [cwRows],
  );
  const issuerOptions = useMemo(
    () => [...new Set(cwRows.map((r) => r.issuer).filter((v): v is string => !!v))].sort(),
    [cwRows],
  );

  const stocks = useSortPin(stockRows, STOCK_FIELDS);
  const cws = useSortPin(cwRows, CW_FIELDS);

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
        <span style={{ fontSize: 10.5, color: "var(--t-42)", fontStyle: "italic" }}>
          “{sessionNote}”
        </span>
        <span className="mono" style={{ fontSize: 10.5, color: "var(--t-46)" }}>
          {plan.symbolCount} / {plan.capacity ?? 33}
        </span>
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

      {stockRows.length > 0 && (
        <table
          className="mono"
          style={{ width: "100%", borderCollapse: "collapse", fontSize: 11.5, marginBottom: 10 }}
        >
          <thead>
            <tr style={{ borderBottom: "1px solid var(--border-strong)" }}>
              <PinHeader />
              <SortHeader label="SYMBOL" align="left" mark={stocks.sortMark("symbol")} onClick={() => stocks.toggleSort("symbol")} />
              <SortHeader label="REF" mark={stocks.sortMark("ref")} onClick={() => stocks.toggleSort("ref")} />
              <SortHeader label="BID" mark={stocks.sortMark("bid")} onClick={() => stocks.toggleSort("bid")} />
              <SortHeader label="ASK" mark={stocks.sortMark("ask")} onClick={() => stocks.toggleSort("ask")} />
              <SortHeader label="TRD" mark={stocks.sortMark("trd")} onClick={() => stocks.toggleSort("trd")} />
              <SortHeader label="CHG%" mark={stocks.sortMark("chg")} onClick={() => stocks.toggleSort("chg")} />
              <SortHeader label="VOLUME" mark={stocks.sortMark("vol")} onClick={() => stocks.toggleSort("vol")} />
              <SortHeader label="FRN BUY" mark={stocks.sortMark("forBuy")} onClick={() => stocks.toggleSort("forBuy")} />
              <SortHeader label="FRN SELL" mark={stocks.sortMark("forSell")} onClick={() => stocks.toggleSort("forSell")} />
              <SortHeader label="FRN ROOM" mark={stocks.sortMark("room")} onClick={() => stocks.toggleSort("room")} />
            </tr>
          </thead>
          <tbody>
            {stocks.ordered.map((r) => {
              const chg = fmtChg(r.chgPct);
              const selected = selectedSymbol === r.symbol;
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
                  <PinCell symbol={r.symbol} fill={stocks.pinFill(r.symbol)} onToggle={stocks.togglePin} />
                  <td style={{ padding: "0 8px", color: "var(--accent)" }}>{r.symbol}</td>
                  <td style={{ ...TD, color: "var(--t-60)" }}>{fmtPrice(r.ref)}</td>
                  <td style={{ ...TD, color: priceColor(r.bid, priceRef(r)) }}>{fmtPrice(r.bid)}</td>
                  <td style={{ ...TD, color: priceColor(r.ask, priceRef(r)) }}>{fmtPrice(r.ask)}</td>
                  <td style={{ ...TD, color: priceColor(r.last, priceRef(r)) }}>{fmtPrice(r.last)}</td>
                  <td style={{ ...TD, color: chg.color }}>{chg.text}</td>
                  <td style={{ ...TD, color: "var(--t-50)" }}>{fmtVol(r.vol)}</td>
                  <td style={{ ...TD, color: "var(--t-60)" }}>{fmtVol(r.forBuy)}</td>
                  <td style={{ ...TD, color: "var(--t-60)" }}>{fmtVol(r.forSell)}</td>
                  <td style={{ ...TD, color: "var(--t-50)" }}>{fmtVol(r.room)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      {cwRows.length > 0 && (
        <table className="mono" style={{ width: "100%", borderCollapse: "collapse", fontSize: 11.5 }}>
          <thead>
            <tr style={{ borderBottom: "1px solid var(--border-strong)" }}>
              <PinHeader />
              <SortHeader label="SYMBOL" align="left" mark={cws.sortMark("symbol")} onClick={() => cws.toggleSort("symbol")} />
              <SortHeader label="UND." align="left" mark={cws.sortMark("und")} onClick={() => cws.toggleSort("und")} />
              <SortHeader label="UND.PRC" mark={cws.sortMark("undPrice")} onClick={() => cws.toggleSort("undPrice")} />
              <SortHeader label="BID" mark={cws.sortMark("bid")} onClick={() => cws.toggleSort("bid")} />
              <SortHeader label="ASK" mark={cws.sortMark("ask")} onClick={() => cws.toggleSort("ask")} />
              <SortHeader label="TRD" mark={cws.sortMark("trd")} onClick={() => cws.toggleSort("trd")} />
              <SortHeader label="CHG%" mark={cws.sortMark("chg")} onClick={() => cws.toggleSort("chg")} />
              <SortHeader label="STRIKE" mark={cws.sortMark("strike")} onClick={() => cws.toggleSort("strike")} />
              <SortHeader label="RATIO" mark={cws.sortMark("ratio")} onClick={() => cws.toggleSort("ratio")} />
              <SortHeader label="DTE" mark={cws.sortMark("dte")} onClick={() => cws.toggleSort("dte")} />
              <SortHeader label="IV BID" mark={cws.sortMark("ivBid")} onClick={() => cws.toggleSort("ivBid")} />
              <SortHeader label="IV TRD" mark={cws.sortMark("ivTrade")} onClick={() => cws.toggleSort("ivTrade")} />
              <SortHeader label="IV ASK" mark={cws.sortMark("ivAsk")} onClick={() => cws.toggleSort("ivAsk")} />
            </tr>
          </thead>
          <tbody>
            {cws.ordered.map((r) => {
              const chg = fmtChg(r.chgPct);
              const selected = selectedSymbol === r.symbol;
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
                  <PinCell symbol={r.symbol} fill={cws.pinFill(r.symbol)} onToggle={cws.togglePin} />
                  <td style={{ padding: "0 8px", color: "var(--accent)", whiteSpace: "nowrap" }}>
                    {r.symbol}
                    {r.conflicting && (
                      <span
                        title="Conflicting metadata — quant withheld"
                        style={{ marginLeft: 5, color: "var(--down)" }}
                      >
                        ◆
                      </span>
                    )}
                  </td>
                  <td style={{ padding: "0 8px", color: "var(--t-60)" }}>{r.underlying ?? DASH}</td>
                  <td style={{ ...TD, color: "var(--t-60)" }}>{fmtPrice(r.undPrice)}</td>
                  <td style={{ ...TD, color: priceColor(r.bid, priceRef(r)) }}>{fmtPrice(r.bid)}</td>
                  <td style={{ ...TD, color: priceColor(r.ask, priceRef(r)) }}>{fmtPrice(r.ask)}</td>
                  <td style={{ ...TD, color: priceColor(r.last, priceRef(r)) }}>{fmtPrice(r.last)}</td>
                  <td style={{ ...TD, color: chg.color }}>{chg.text}</td>
                  <td style={{ ...TD, color: "var(--t-60)" }}>{fmtPrice(r.strike)}</td>
                  <td style={{ ...TD, color: "var(--t-50)" }}>{fmtRatio(r.ratio)}</td>
                  <td style={{ ...TD, color: "var(--t-46)" }}>{r.dteText}</td>
                  <td style={{ ...TD, color: "var(--t-50)" }}>{fmtIV(r.ivBid)}</td>
                  <td style={{ ...TD, color: "var(--accent)" }}>{fmtIV(r.ivTrade)}</td>
                  <td style={{ ...TD, color: "var(--t-50)" }}>{fmtIV(r.ivAsk)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
