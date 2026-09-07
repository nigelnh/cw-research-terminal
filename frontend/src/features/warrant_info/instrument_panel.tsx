import { useEffect, useState } from "react";
import type { RealtimePulse } from "@/domain/models";
import type { SelectedInstrumentView } from "@/data/selected_instrument";
import type { DashboardRow } from "@/data/query/use_dashboard_data";
import type { ResearchContextEnvelope } from "@/data/ai/use_ai_chat";
import type { CorporateActionItem } from "@/domain/models";
import { useWatchlist } from "@/data/watchlist";
import { useHistoricalBars, useCorporateActions } from "@/data/query";
import { useTradedLog } from "@/data/query/use_traded_log";
import { useFundamentals } from "@/data/query/use_fundamentals";
import { QuarterlyResultsChart } from "./quarterly_results_chart";
import { TradingChart } from "@/components/common/trading_chart";
import { DASH, fmtIV, fmtPrice, fmtVol, dteDisplay } from "@/components/common/grid_table";
import { RealtimeValue, type FlashTone } from "@/components/common/realtime_value";

import { QUOTE_COLUMNS, QUOTE_COLUMN_HINTS, QUOTE_COLUMN_PULSE_FIELD, quoteCell, type QuoteTableValues } from "@/components/common/quote_columns";
import { useWatchlistLayout } from "@/components/common/watchlist_layout";

interface InstrumentPanelProps {
  instrument: SelectedInstrumentView | null;
  dashRow?: DashboardRow;
  marketSessionActive: boolean;
  context?: ResearchContextEnvelope;
  onClose: () => void;
  /** Test-only: force the initial sub-tab. Production always starts on "overview". */
  initialTab?: "overview" | "quant";
}

/* ---------------------------------------------------------------- helpers */

const LABEL: React.CSSProperties = { fontSize: 10, color: "var(--t-46)" };

function MetricRow({
  label,
  value,
  color = "var(--t-92)",
  size = 13,
  compact = false,
  title,
  pulse,
  tone,
}: {
  label: string;
  value: React.ReactNode;
  color?: string;
  size?: number;
  compact?: boolean;
  title?: string;
  pulse?: RealtimePulse;
  tone?: FlashTone;
}) {
  return (
    <div
      title={title}
      className={compact ? "instrument-metric" : undefined}
      style={{
        display: "flex",
        justifyContent: "space-between",
        padding: compact ? "2px 0" : "5px 0",
        lineHeight: compact ? "15px" : undefined,
      }}
    >
      <span style={{ ...LABEL, fontSize: compact ? 11 : size }}>{label}</span>
      <span style={{ fontSize: compact ? 11 : size, color }}>
        <RealtimeValue pulse={pulse} tone={tone} style={{ color }}>{value}</RealtimeValue>
      </span>
    </div>
  );
}

function greek(v: number | null | undefined, dp = 2): string {
  if (typeof v !== "number" || Number.isNaN(v)) return DASH;
  return v.toFixed(dp);
}

/* -------------------------------------------------- corporate-events display */

const CORP_EVENT_LABELS: Record<string, string> = {
  CASH_DIVIDEND: "CASH DIV",
  STOCK_DIVIDEND: "STOCK DIV",
  BONUS_ISSUE: "BONUS",
  RIGHTS_ISSUE: "RIGHTS",
  AGM: "AGM",
  EGM: "EGM",
  LISTING: "LISTING",
  DELISTING: "DELISTING",
  OTHER: "OTHER",
};

function corpEventLabel(t: string): string {
  return CORP_EVENT_LABELS[t] ?? t;
}

function isoDay(v: string | null | undefined): string {
  if (!v) return DASH;
  return v.slice(0, 10);
}

function corpEventDesc(ev: CorporateActionItem): string {
  if (ev.action_type === "CASH_DIVIDEND" && typeof ev.cash_amount_vnd === "number") {
    return `${Math.round(ev.cash_amount_vnd).toLocaleString("en-US")} VND/sh`;
  }
  if (ev.ratio_text) return ev.ratio_text;
  if (typeof ev.ratio_pct === "number") return `${ev.ratio_pct}%`;
  // the raw `note` is Vietnamese — not shown as a primary UI label (LANGUAGE_POLICY.md)
  return DASH;
}

/** Named, not silently blank: this tier's get_ratios returns only revenue, net profit and
 *  EBIT, and an explicit `fields` list makes the SDK raise, so these have no source. */
const UNAVAILABLE_HINT =
  "Not served by the current market-data entitlement — no source for this figure.";
const TS_COLS = "1.1fr 1fr 1fr 1.15fr 1fr 0.65fr";

const TS_HEAD: React.CSSProperties = {
  textAlign: "right",
  borderRight: "1px solid var(--border-row)",
  paddingRight: 4,
};

/**
 * TRADED LOGS panel (OVERVIEW tab) - server-side time & sales.
 *
 * The tape is kept until 08:00 ICT the morning after its session, so this stays populated
 * after the close instead of going blank at 15:00. The B/S column is DERIVED from the last
 * known book (at/through the ask = buyer crossed, at/through the bid = seller); a print
 * inside the spread is left blank rather than guessed, and the header says so.
 */
function TimeSalesPanel({ symbol, live }: { symbol: string; live: boolean }) {
  const { items, isLoading, isError } = useTradedLog(symbol, live);
  const cellStyle: React.CSSProperties = { textAlign: "right", fontVariantNumeric: "tabular-nums" };
  const note = isError
    ? "Traded logs unavailable."
    : isLoading
      ? "Loading…"
      : live
        ? "No matches yet this session."
        : "No matches recorded for the last session.";

  return (
    <div className="mono instrument-data-panel">
      <h3 className="instrument-section-heading">TRADED LOGS</h3>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: TS_COLS,
          gap: "2px 6px",
          fontSize: 9,
          color: "var(--t-42)",
          padding: "5px 8px",
          borderTop: "1px solid var(--border-mid)",
          borderBottom: "1px solid var(--border-mid)",
        }}
      >
        <span style={{ borderRight: "1px solid var(--border-row)", paddingRight: 4 }}>TIME</span>
        <span style={TS_HEAD}>TRD_PRC</span>
        <span style={TS_HEAD}>+/-</span>
        <span style={TS_HEAD}>%CHG</span>
        <span style={TS_HEAD}>VOL</span>
        <span style={{ textAlign: "right" }} title="Aggressor side, derived from the order book. The exchange publishes no per-match buy/sell flag, so a print inside the spread is left blank.">
          B/S
        </span>
      </div>
      {items.length === 0 ? (
        <div style={{ fontSize: 10.5, color: "var(--t-42)", padding: "8px 10px", lineHeight: 1.5 }}>
          {note}
        </div>
      ) : (
        <div className="instrument-tape">
          {items.map((row) => {
            const tone =
              row.change == null || row.change === 0
                ? "var(--flat)"
                : row.change > 0
                  ? "var(--up)"
                  : "var(--down)";
            return (
              <div key={`${row.ts}:${row.price}:${row.volume ?? ""}`} className="instrument-tape-row">
                <span style={{ borderRight: "1px solid var(--border-row)", paddingRight: 4, color: "var(--t-70)" }}>
                  {row.time}
                </span>
                <span style={{ ...cellStyle, color: tone }}>{fmtPrice(row.price)}</span>
                <span style={{ ...cellStyle, color: tone }}>
                  {row.change == null ? DASH : `${row.change > 0 ? "+" : row.change < 0 ? "\u2212" : ""}${fmtPrice(Math.abs(row.change))}`}
                </span>
                <span style={{ ...cellStyle, color: tone }}>
                  {row.change_percent == null ? DASH : `${row.change_percent > 0 ? "+" : ""}${(row.change_percent * 100).toFixed(2)}%`}
                </span>
                <span style={{ ...cellStyle, color: "var(--t-92)" }}>{fmtVol(row.volume)}</span>
                <span
                  style={{
                    textAlign: "right",
                    color: row.side === "B" ? "var(--up)" : row.side === "S" ? "var(--down)" : "var(--t-42)",
                  }}
                >
                  {row.side ?? DASH}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

/* ---------------------------------------------------------------- panel */

export function InstrumentPanel({
  instrument,
  dashRow,
  marketSessionActive,
  onClose,
  initialTab = "overview",
}: InstrumentPanelProps) {
  const { isInWatchlist, addToWatchlist, removeFromWatchlist, canAdd } = useWatchlist();
  const [tab, setTab] = useState<"overview" | "quant">(initialTab);
  const [addNote, setAddNote] = useState<string | null>(null);

  const hasInstrument = !!instrument;
  const isCW = instrument?.instrumentType === "CW";
  const isIndex = instrument?.instrumentType === "INDEX";
  const symbol = instrument?.symbol ?? null;

  useEffect(() => {
    setTab("overview");
    setAddNote(null);
  }, [symbol]);

  const tableLayout = useWatchlistLayout();

  // Daily bars, ~6 months of recent sessions. "1D" is the bar INTERVAL; the "6M"
  // timeframe is the client-side window over the Postgres-first `daily_1y` dataset
  // (same backend call as any other daily request — no extra provider traffic).
  const bars = useHistoricalBars({
    symbol: symbol ?? undefined,
    timeframe: "6M",
    interval: "1D",
    adjusted: false,
    enabled: hasInstrument && !isIndex,
  });

  // Corporate actions apply to the underlying company — stocks only, and only when
  // the QUANT tab (which hosts the CORPORATE EVENTS table) is actually open.
  const corpActions = useCorporateActions(symbol, {
    enabled: hasInstrument && !isCW && !isIndex && tab === "quant",
    limit: 12,
  });

  // Fundamentals belong to the company, so a CW reads its underlying's. Fetched only while
  // the QUANT tab is open - this is a once-a-day/once-a-quarter read, not a ticking one.
  const fundamentalsSymbol = isCW ? (instrument?.underlyingSymbol ?? null) : symbol;
  const fundamentals = useFundamentals(
    fundamentalsSymbol,
    hasInstrument && !isIndex && tab === "quant",
  );
  const valuationHint = fundamentals.data?.valuation_as_of
    ? `Trailing, as of ${fundamentals.data.valuation_as_of}`
    : "Trailing valuation from the market-data provider";

  const cw = instrument?.cw;
  const q = dashRow?.quote ?? instrument?.quote ?? cw?.quote;
  const an = dashRow?.analytics ?? null;

  const ref = q?.referencePrice ?? null;
  const pick = (k: string): number | null => {
    const fromCw = (cw as Record<string, unknown> | undefined)?.[k];
    if (typeof fromCw === "number") return fromCw;
    const fromAn = (an as Record<string, unknown> | null)?.[k];
    if (typeof fromAn === "number") return fromAn;
    return null;
  };
  const moneynessCat =
    cw?.moneynessCategory ?? (an as { moneynessCategory?: string } | null)?.moneynessCategory ?? null;

  const conflicting = instrument?.metadataVerification === "CONFLICTING";

  const kindLine = !instrument
    ? ""
    : isCW
    ? `COVERED WARRANT · ${instrument.issuer ?? "—"} · ${instrument.underlyingSymbol ?? "—"}`
    : isIndex
    ? "INDEX · HOSE"
    : "STOCK · HOSE";

  const watched = symbol ? isInWatchlist(symbol) : false;

  const toggleWatch = () => {
    if (!instrument) return;
    setAddNote(null);
    if (watched) {
      removeFromWatchlist(instrument.symbol);
      return;
    }
    const type = isCW ? "CW" : isIndex ? "INDEX" : "STOCK";
    const check = canAdd({
      symbol: instrument.symbol,
      instrumentType: type,
      underlyingSymbol: instrument.underlyingSymbol,
    });
    if (!check.allowed && check.reason) {
      setAddNote(check.reason);
      return;
    }
    const res = addToWatchlist({
      symbol: instrument.symbol,
      instrumentType: type,
      underlyingSymbol: instrument.underlyingSymbol,
      issuer: instrument.issuer,
      strikePrice: instrument.strikePrice,
      exerciseRatio: instrument.exerciseRatio,
      maturityDate: instrument.maturityDate,
      lastTradingDate: instrument.lastTradingDate,
    });
    if (!res.success && res.reason) setAddNote(res.reason);
  };

  const tabBtn = (id: "overview" | "quant"): React.CSSProperties => ({
    padding: "3px 10px",
    border: "none",
    borderRadius: 2,
    cursor: "pointer",
    fontFamily: "inherit",
    fontSize: 10.5,
    background: tab === id ? "var(--panel-tab-active)" : "transparent",
    color: tab === id ? "var(--t-92)" : "var(--t-55)",
  });

  const stats: QuoteTableValues = {
    symbol: instrument?.symbol ?? "", ref, ceiling: q?.ceilingPrice ?? null, floor: q?.floorPrice ?? null,
    bid: q?.bidPrice ?? null, ask: q?.askPrice ?? null, last: q?.lastPrice ?? null,
    tradedQuantity: q?.tradedQuantity ?? null,
    change: q?.priceChange ?? null,
    issuer: isCW ? instrument?.issuer ?? null : null,
    chgPct: typeof q?.priceChangePercent === "number" ? q.priceChangePercent * 100 : null,
    vol: q?.totalVolume ?? null, strike: isCW ? instrument?.strikePrice ?? null : null,
    ratio: isCW ? instrument?.exerciseRatio ?? null : null,
    lastTradingDate: isCW ? instrument?.lastTradingDate ?? null : null,
    ivBid: isCW ? pick("ivBid") : null, ivTrade: isCW ? pick("ivTrade") : null, ivAsk: isCW ? pick("ivAsk") : null,
    dteText: isCW ? dteDisplay(instrument?.lastTradingDate, instrument?.maturityDate, an?.dte) : DASH,
  };

  // No instrument selected -> render nothing. The AI assistant now lives entirely in the
  // draggable Orbit panel; Dashboard / Research reclaim the vertical space.
  if (!instrument) return null;

  return (
    <section
      style={{
        height: "min(410px, 58vh)",
        flexShrink: 0,
        borderTop: "1px solid var(--border-strong)",
        display: "flex",
        flexDirection: "column",
        background: "var(--panel)",
      }}
    >
      {/* header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 16,
          padding: "0 20px",
          height: 34,
          borderBottom: "1px solid var(--border)",
          flexShrink: 0,
        }}
      >
        {(
          <>
            <span className="heading" style={{ fontSize: 13, color: quoteCell(stats, "symbol").color, fontWeight: 700 }}>
              {instrument.symbol}
            </span>
            <span style={{ fontSize: 13, color: "var(--t-50)" }}>{kindLine}</span>
            <div style={{ display: "flex", gap: 2, marginLeft: 12 }}>
              <button type="button" onClick={() => setTab("overview")} style={tabBtn("overview")}>
                OVERVIEW
              </button>
              <button type="button" onClick={() => setTab("quant")} style={tabBtn("quant")}>
                QUANT
              </button>
            </div>
            <button
              type="button"
              onClick={toggleWatch}
              className="focus-ring"
              style={{
                marginLeft: "auto",
                padding: "3px 10px",
                borderRadius: 2,
                border: "1px solid var(--border-30)",
                cursor: "pointer",
                fontFamily: "inherit",
                fontSize: 10.5,
                background: "transparent",
                color: watched ? "var(--accent)" : "var(--t-60)",
              }}
            >
              {watched ? "WATCHING" : "+ WATCH"}
            </button>
            <button
              type="button"
              onClick={onClose}
              className="focus-ring"
              aria-label="Close instrument"
              style={{ background: "none", border: "none", cursor: "pointer", color: "var(--t-50)", padding: 2 }}
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
                <path d="M18 6 6 18M6 6l12 12" />
              </svg>
            </button>
          </>
        )}
      </div>

      {hasInstrument && addNote && (
        <div style={{ padding: "6px 20px 0 20px", fontSize: 10.5, color: "var(--t-55)" }}>{addNote}</div>
      )}

      {/* OVERVIEW */}
      {hasInstrument && tab === "overview" && (
        <div style={{ flex: 1, overflowY: "auto", padding: "14px 20px", display: "flex", gap: 22, minHeight: 0 }}>
          <div className="mono" style={{ width: 220, flexShrink: 0, overflowY: "auto" }}>
            <h3 className="instrument-section-heading">STATS</h3>
            {tableLayout.columns.filter(key => {
              if (key === "symbol") return false;
              if (!isCW && ["ivBid", "ivTrade", "ivAsk", "strike", "ratio", "lastTradingDate", "dte", "issuer"].includes(key)) return false;
              return !(isCW && key === "issuer");
            }).map(key => {
              const column = QUOTE_COLUMNS.find(c => c.key === key)!;
              const cell = quoteCell(stats, key);
              const pulseField = QUOTE_COLUMN_PULSE_FIELD[key];
              const pulse = pulseField
                ? (cw?.realtimePulses?.[pulseField] ?? q?.realtimePulses?.[pulseField])
                : undefined;
              return <MetricRow key={key} label={column.label} value={cell.text} color={cell.color} tone={cell.tone} compact title={QUOTE_COLUMN_HINTS[key]} pulse={pulse} />;
            })}
            {conflicting && (
              <div
                style={{
                  marginTop: 12,
                  padding: "10px 12px",
                  border: "1px solid var(--border-30)",
                  fontSize: 11,
                  color: "var(--t-66)",
                  lineHeight: 1.6,
                }}
              >
                <strong style={{ color: "var(--t-90)" }}>CONFLICTING METADATA</strong> — effective
                terms disagree across public sources. Quant withheld until reconciled.
              </div>
            )}
          </div>

          <div style={{ flex: 1, minWidth: 0, minHeight: 0, display: "flex", gap: 16 }}>
            <div
              style={{
                flex: 1,
                minWidth: 0,
                height: "100%",
                border: "1px solid var(--border)",
                display: "flex",
              }}
            >
              {bars.isLoading || bars.isEmpty || bars.bars.length === 0 ? (
                <div style={{ margin: "auto", fontSize: 11, color: "var(--t-42)" }}>
                  {bars.isLoading ? "loading daily bars…" : "no daily history"}
                </div>
              ) : (
                <TradingChart
                  symbol={instrument!.symbol}
                  isCW={isCW}
                  bars={bars.bars}
                  liveQuote={marketSessionActive ? q ?? null : null}
                  interval="1D"
                  referencePrice={ref}
                  height={300}
                />
              )}
            </div>
            {!isIndex && <TimeSalesPanel symbol={instrument.symbol} live={marketSessionActive} />}
          </div>
        </div>
      )}

      {/* QUANT */}
      {hasInstrument && tab === "quant" && (
        <div style={{ flex: 1, overflowY: "auto", padding: "14px 20px", display: "flex", gap: 22, minHeight: 0 }}>
          {isCW ? (
            <>
              <div className="mono" style={{ width: 220, flexShrink: 0, overflowY: "auto" }}>
                <h3 className="instrument-section-heading">OPTIONS ANALYTICS</h3>
                <MetricRow label="IV_BID" color="var(--t-85)" compact value={fmtIV(pick("ivBid"))} pulse={cw?.realtimePulses?.ivBid} />
                <MetricRow label="IV_TRD" color="var(--t-85)" compact value={fmtIV(pick("ivTrade"))} pulse={cw?.realtimePulses?.ivTrade} />
                <MetricRow label="IV_ASK" color="var(--t-85)" compact value={fmtIV(pick("ivAsk"))} pulse={cw?.realtimePulses?.ivAsk} />
                <MetricRow label="HV22" color="var(--t-85)" compact value={fmtIV(pick("historicalVolatility"))} pulse={cw?.realtimePulses?.historicalVolatility} />
                <MetricRow label="MONEYNESS S/K" color="var(--t-85)" compact
                  value={pick("moneynessRatio") !== null ? pick("moneynessRatio")!.toFixed(3) : DASH} pulse={cw?.realtimePulses?.moneynessRatio} />
                <MetricRow label="MONEYNESS" color="var(--t-85)" compact value={moneynessCat ?? DASH} />
                <MetricRow label="THEO_PRC" color="var(--t-85)" compact value={fmtPrice(pick("theoreticalPrice"))} pulse={cw?.realtimePulses?.theoreticalPrice} />
                <MetricRow label="DELTA" color="var(--t-85)" compact value={greek(pick("delta"), 4)} pulse={cw?.realtimePulses?.delta} />
                <MetricRow label="GAMMA" color="var(--t-85)" compact value={greek(pick("gamma"), 6)} pulse={cw?.realtimePulses?.gamma} />
                <MetricRow label="THETA/DAY" color="var(--t-85)" compact value={greek(pick("theta"), 2)} pulse={cw?.realtimePulses?.theta} />
                <MetricRow label="VEGA /1%" color="var(--t-85)" compact value={greek(pick("vega"), 2)} pulse={cw?.realtimePulses?.vega} />
                <MetricRow label="RHO /1%" color="var(--t-85)" compact value={greek(pick("rho"), 2)} pulse={cw?.realtimePulses?.rho} />
              </div>
              <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 8 }}>
                {marketSessionActive ? (
                  <div style={{ display: "flex", gap: 8, height: "100%" }}>
                    <div style={{ flex: 1, border: "1px solid var(--border)", display: "flex", alignItems: "center", justifyContent: "center" }}>
                      <span style={{ fontSize: 10.5, color: "var(--t-42)" }}>PRICE DEPTH · live</span>
                    </div>
                    <div style={{ flex: 1, border: "1px solid var(--border)", display: "flex", alignItems: "center", justifyContent: "center" }}>
                      <span style={{ fontSize: 10.5, color: "var(--t-42)" }}>MARKET DEPTH · live</span>
                    </div>
                  </div>
                ) : (
                  <div
                    style={{
                      height: "100%",
                      border: "1px solid var(--border)",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      padding: 20,
                      textAlign: "center",
                    }}
                  >
                    <span style={{ fontSize: 11, color: "var(--t-42)" }}>
                      Order book depth &amp; time-of-sale unavailable outside a live session
                    </span>
                  </div>
                )}
              </div>
            </>
          ) : (
            <>
              <div className="mono" style={{ width: 220, flexShrink: 0 }}>
                <h3 className="instrument-section-heading">FINANCIAL INDICATORS</h3>
                {isIndex ? (
                  <div style={{ fontSize: 11, color: "var(--t-42)", padding: "8px 0" }}>
                    No fundamentals — index.
                  </div>
                ) : (
                  <>
                    <MetricRow label="EPS" color="var(--t-85)" compact value={DASH} title={UNAVAILABLE_HINT} />
                    <MetricRow
                      label="PE"
                      color="var(--t-85)"
                      compact
                      value={fundamentals.data?.pe == null ? DASH : fundamentals.data.pe.toFixed(2)}
                      title={valuationHint}
                    />
                    <MetricRow
                      label="PB"
                      color="var(--t-85)"
                      compact
                      value={fundamentals.data?.pb == null ? DASH : fundamentals.data.pb.toFixed(2)}
                      title={valuationHint}
                    />
                    <MetricRow label="ROE" color="var(--t-85)" compact value={DASH} title={UNAVAILABLE_HINT} />
                    <MetricRow label="ROA" color="var(--t-85)" compact value={DASH} title={UNAVAILABLE_HINT} />
                    <MetricRow label="ROIC" color="var(--t-85)" compact value={DASH} title={UNAVAILABLE_HINT} />
                    <MetricRow label="GROSS MARGIN" color="var(--t-85)" compact value={DASH} title={UNAVAILABLE_HINT} />
                    <MetricRow
                      label="NET MARGIN"
                      color="var(--t-85)"
                      compact
                      value={
                        fundamentals.data?.net_margin == null
                          ? DASH
                          : `${(fundamentals.data.net_margin * 100).toFixed(1)}%`
                      }
                      title={
                        fundamentals.data?.latest_period
                          ? `Net profit / revenue, ${fundamentals.data.latest_period} (consolidated)`
                          : "Net profit / revenue for the latest reported quarter"
                      }
                    />
                  </>
                )}
              </div>
              <div style={{ flex: 1, minWidth: 0, minHeight: 0, display: "flex", gap: 16 }}>
                <QuarterlyResultsChart
                  rows={fundamentals.quarters}
                  isLoading={fundamentals.isLoading}
                  isError={fundamentals.isError}
                />
                {!isIndex && (
                  <div className="mono instrument-data-panel">
                    <h3 className="instrument-section-heading">CORPORATE EVENTS</h3>
                    <table className="instrument-data-table corporate-events-table" aria-label="Corporate events">
                      <colgroup>
                        <col className="event-type-column" />
                        <col className="event-date-column" />
                        <col className="event-date-column" />
                        <col />
                      </colgroup>
                      <thead>
                        <tr>
                          <th scope="col">EVENT TYPE</th>
                          <th scope="col">EX-DIV</th>
                          <th scope="col">ISSUE</th>
                          <th scope="col">DESC</th>
                        </tr>
                      </thead>
                      <tbody>
                        {corpActions.isLoading ? (
                          <tr>
                            <td colSpan={4} className="instrument-data-state">loading…</td>
                          </tr>
                        ) : corpActions.isError ? (
                          <tr>
                            <td colSpan={4} className="instrument-data-state" style={{ color: "var(--down)" }}>
                              corporate-events feed unavailable
                            </td>
                          </tr>
                        ) : corpActions.items.length === 0 ? (
                          <tr>
                            <td colSpan={4} className="instrument-data-state">
                              {DASH} no corporate events on record for {symbol}
                            </td>
                          </tr>
                        ) : (
                          corpActions.items.map((ev) => (
                            <tr key={ev.id}>
                              <td style={{ color: "var(--t-80)" }}>{ev.event_label || corpEventLabel(ev.action_type)}</td>
                              <td style={{ color: "var(--t-55)" }}>{isoDay(ev.ex_date)}</td>
                              <td style={{ color: "var(--t-50)" }}>{isoDay(ev.record_date ?? ev.disclosure_date)}</td>
                              <td style={{ color: "var(--t-60)" }}>{corpEventDesc(ev)}</td>
                            </tr>
                          ))
                        )}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      )}
    </section>
  );
}
