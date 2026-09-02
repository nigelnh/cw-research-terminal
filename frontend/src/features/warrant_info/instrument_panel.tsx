import { useEffect, useState } from "react";
import type { SelectedInstrumentView } from "@/data/selected_instrument";
import type { DashboardRow } from "@/data/query/use_dashboard_data";
import type { ResearchContextEnvelope } from "@/data/ai/use_ai_chat";
import type { CorporateActionItem } from "@/domain/models";
import { useWatchlist } from "@/data/watchlist";
import { useHistoricalBars, useCorporateActions } from "@/data/query";
import { TradingChart } from "@/components/common/trading_chart";
import { DASH, fmtIV, fmtPrice, dteDisplay } from "@/components/common/grid_table";

import { QUOTE_COLUMNS, QUOTE_COLUMN_HINTS, quoteCell, type QuoteTableValues } from "@/components/common/quote_columns";
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
}: {
  label: string;
  value: React.ReactNode;
  color?: string;
  size?: number;
  compact?: boolean;
  title?: string;
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
      <span style={{ fontSize: compact ? 11 : size, color }}>{value}</span>
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

const TS_COLS = "1.1fr 1fr 1fr 1.15fr 1fr 0.65fr";

const TS_HEAD: React.CSSProperties = {
  textAlign: "right",
  borderRight: "1px solid var(--border-row)",
  paddingRight: 4,
};

/**
 * TRADED LOGS panel (OVERVIEW tab). There is no live trade feed yet, so this is an
 * honest empty state — session-gated per the UX data contract. Tracked as a follow-up.
 */
function TimeSalesPanel({ live }: { live: boolean }) {
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
        <span style={{ textAlign: "right" }}>B/S</span>
      </div>
      <div style={{ fontSize: 10.5, color: "var(--t-42)", padding: "8px 10px", lineHeight: 1.5 }}>
        {live
          ? "Live trade feed not yet wired — pending backend support."
          : "Traded logs unavailable outside a live session."}
      </div>
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
    adjusted: true,
    enabled: hasInstrument && !isIndex,
  });

  // Corporate actions apply to the underlying company — stocks only, and only when
  // the QUANT tab (which hosts the CORPORATE EVENTS table) is actually open.
  const corpActions = useCorporateActions(symbol, {
    enabled: hasInstrument && !isCW && !isIndex && tab === "quant",
    limit: 12,
  });

  const cw = instrument?.cw;
  const q = instrument?.quote ?? cw?.quote ?? dashRow?.quote;
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
    tradingValue: q?.tradingValue ?? null,
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
            <span className="heading" style={{ fontSize: 13, color: "var(--accent)", fontWeight: 700 }}>
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
            {tableLayout.columns.filter(key => key !== "symbol").map(key => {
              const column = QUOTE_COLUMNS.find(c => c.key === key)!;
              const cell = quoteCell(stats, key);
              return <MetricRow key={key} label={column.label} value={cell.text} color={cell.color} compact title={QUOTE_COLUMN_HINTS[key]} />;
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
            {!isIndex && <TimeSalesPanel live={marketSessionActive} />}
          </div>
        </div>
      )}

      {/* QUANT */}
      {hasInstrument && tab === "quant" && (
        <div style={{ flex: 1, overflowY: "auto", padding: "14px 20px", display: "flex", gap: 22, minHeight: 0 }}>
          {isCW ? (
            <>
              <div className="mono" style={{ width: 220, flexShrink: 0, display: "flex", flexDirection: "column", gap: 2 }}>
                <MetricRow
                  label="IV BID·TRD·ASK"
                  color="var(--t-85)"
                  size={11}
                  value={`${fmtIV(pick("ivBid"))} · ${fmtIV(pick("ivTrade"))} · ${fmtIV(pick("ivAsk"))}`}
                />
                <MetricRow label="HV22" color="var(--t-85)" size={11} value={fmtIV(pick("historicalVolatility"))} />
                <MetricRow
                  label="MONEYNESS S/K"
                  color="var(--t-85)"
                  size={11}
                  value={
                    pick("moneynessRatio") !== null
                      ? `${pick("moneynessRatio")!.toFixed(3)}${moneynessCat ? ` · ${moneynessCat}` : ""}`
                      : DASH
                  }
                />
                <MetricRow label="THEO PRICE" color="var(--t-85)" size={11} value={fmtPrice(pick("theoreticalPrice"))} />
                <MetricRow label="DELTA" color="var(--t-85)" size={11} value={greek(pick("delta"), 4)} />
                <MetricRow label="GAMMA" color="var(--t-85)" size={11} value={greek(pick("gamma"), 6)} />
                <MetricRow label="THETA/DAY" color="var(--t-85)" size={11} value={greek(pick("theta"), 2)} />
                <MetricRow
                  label="VEGA·RHO /1%"
                  color="var(--t-85)"
                  size={11}
                  value={`${greek(pick("vega"), 2)} · ${greek(pick("rho"), 2)}`}
                />
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
                    <MetricRow label="EPS" color="var(--t-85)" compact value={DASH} />
                    <MetricRow label="PE" color="var(--t-85)" compact value={DASH} />
                    <MetricRow label="PB" color="var(--t-85)" compact value={DASH} />
                    <MetricRow label="ROE" color="var(--t-85)" compact value={DASH} />
                    <MetricRow label="ROA" color="var(--t-85)" compact value={DASH} />
                    <MetricRow label="ROIC" color="var(--t-85)" compact value={DASH} />
                    <MetricRow label="GROSS MARGIN" color="var(--t-85)" compact value={DASH} />
                    <MetricRow label="NET MARGIN" color="var(--t-85)" compact value={DASH} />
                  </>
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
                    flexDirection: "column",
                    alignItems: "center",
                    justifyContent: "center",
                    gap: 4,
                    padding: 8,
                    textAlign: "center",
                  }}
                >
                  <span style={{ fontSize: 11, color: "var(--t-42)" }}>
                    revenue &amp; profit, quarterly (billion VND)
                  </span>
                  <span style={{ fontSize: 9, color: "var(--t-40)" }}>
                    financial-statement data — pending data provider
                  </span>
                </div>
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
