import { useEffect, useMemo, useRef, useState } from "react";
import { Maximize2, Minimize2, X } from "lucide-react";
import type { SelectedInstrumentView } from "@/data/selected_instrument";
import type { DashboardRow } from "@/data/query/use_dashboard_data";
import type { ResearchContextEnvelope } from "@/data/ai/use_ai_chat";
import { useWatchlist } from "@/data/watchlist";
import { useQuote } from "@/data/use_research_market";
import { useHistoricalBars, useCorporateActions } from "@/data/query";
import { sliceBars } from "@/data/query/historical_bars";
import type {
  CWHistoryMode,
  TechnicalOverlay,
} from "@/domain/historical/types";
import { TradingChart } from "@/components/common/trading_chart";
import {
  DASH,
  dteDisplay,
  fmtChg,
  fmtIV,
  fmtPrice,
  fmtRatio,
  fmtSigned,
  fmtVol,
} from "@/components/common/grid_table";
import {
  EmptyState,
  HelpLabel,
  Notice,
  UndoNotice,
  useStoredState,
} from "@/components/common/ui";
import { formatAsOf, quoteTimestamp, temporalLabel } from "@/domain/temporal";

interface Props {
  instrument: SelectedInstrumentView | null;
  dashRow?: DashboardRow;
  marketSessionActive: boolean;
  context?: ResearchContextEnvelope;
  onClose: () => void;
  initialTab?: "overview" | "quant";
}
function Metric({
  label,
  value,
  help,
  color,
}: {
  label: string;
  value: React.ReactNode;
  help?: string;
  color?: string;
}) {
  return (
    <div className="metric">
      <dt>
        {help ? <HelpLabel description={help}>{label}</HelpLabel> : label}
      </dt>
      <dd className="mono" style={{ color }}>
        {value}
      </dd>
    </div>
  );
}
function greek(v: number | null, dp = 4) {
  return v === null ? DASH : v.toFixed(dp);
}
export function InstrumentPanel({
  instrument,
  dashRow,
  marketSessionActive,
  context,
  onClose,
  initialTab = "overview",
}: Props) {
  const { isInWatchlist, addToWatchlist, removeFromWatchlist, canAdd } =
    useWatchlist();
  const addCurrent = useRef(addToWatchlist);
  addCurrent.current = addToWatchlist;
  const [tab, setTab] = useState<"overview" | "quant">(initialTab);
  const [note, setNote] = useState<string | null>(null);
  const [undo, setUndo] = useState<(() => void) | null>(null);
  const [storedHeight, setHeight] = useStoredState("cw:detail:height", 440);
  const [expanded, setExpanded] = useState(false);
  const [range, setRange] = useState("6M");
  const [mode, setMode] = useState<CWHistoryMode>("CW");
  const [overlays, setOverlays] = useState<Set<TechnicalOverlay>>(new Set());
  const bodyRef = useRef<HTMLDivElement>(null);
  const [chartHeight, setChartHeight] = useState(270);
  const symbol = instrument?.symbol ?? null;
  const isCW = instrument?.instrumentType === "CW";
  const isIndex = instrument?.instrumentType === "INDEX";
  useEffect(() => {
    setTab(initialTab);
    setNote(null);
    setUndo(null);
    setMode("CW");
  }, [symbol, initialTab]);
  const history = useHistoricalBars({
    symbol,
    timeframe: "1Y",
    interval: "1D",
    adjusted: !isCW,
    enabled: !!symbol,
  });
  const underlying = useHistoricalBars({
    symbol: instrument?.underlyingSymbol,
    timeframe: "1Y",
    interval: "1D",
    adjusted: true,
    enabled:
      !!symbol && !!instrument?.underlyingSymbol && isCW && mode !== "CW",
  });
  const bars = useMemo(
    () => sliceBars(history.bars, range),
    [history.bars, range],
  );
  const underlyingBars = useMemo(
    () => sliceBars(underlying.bars, range),
    [underlying.bars, range],
  );
  const events = useCorporateActions(symbol, {
    enabled: !!symbol && !isCW && !isIndex && tab === "quant",
    limit: 30,
  });
  useEffect(() => {
    const el = bodyRef.current;
    if (!el) return;
    // Measure the panel's fixed viewport, never a wrapper sized by this chart.
    // A wrapping chart header would otherwise grow its own ResizeObserver input.
    const measure = () => setChartHeight(Math.max(220, el.clientHeight - 170));
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    measure();
    return () => observer.disconnect();
  }, [symbol, tab, expanded]);
  const underlyingQuote = useQuote(instrument?.underlyingSymbol);
  const cw = instrument?.cw;
  const q = dashRow?.quote ?? instrument?.quote ?? cw?.quote;
  const live = dashRow?.displayState === "LIVE" && marketSessionActive;
  const an = dashRow?.analytics;
  const conflicting = instrument?.metadataVerification === "CONFLICTING";
  const withheld =
    conflicting ||
    (live
      ? cw?.quantAvailable === false || !!cw?.quantUnavailableReason
      : an?.isAvailable === false);
  const pick = (key: string): number | null => {
    if (withheld) return null;
    const v = live
      ? ((cw as unknown as Record<string, unknown> | undefined)?.[key] ??
        an?.[key])
      : an?.[key];
    return typeof v === "number" && Number.isFinite(v) ? v : null;
  };
  const pct =
    typeof q?.priceChangePercent === "number"
      ? q.priceChangePercent * 100
      : null;
  const change = fmtChg(pct);
  const amount =
    q?.lastPrice != null && q?.referencePrice != null
      ? q.lastPrice - q.referencePrice
      : null;
  const stamp =
    dashRow?.provenance.quote.asOf ??
    dashRow?.provenance.quote.sessionDate ??
    quoteTimestamp(q) ??
    context?.quoteAsOf;
  const analyticsStamp =
    dashRow?.provenance.analytics?.asOf ??
    dashRow?.provenance.analytics?.sessionDate ??
    (live ? cw?.analyticsCalculatedAt : null);
  const state = dashRow?.displayState ?? "UNAVAILABLE";
  const height = Math.min(680, Math.max(300, Number(storedHeight) || 440));
  const resize = (e: React.PointerEvent<HTMLDivElement>) => {
    e.currentTarget.setPointerCapture(e.pointerId);
  };
  const drag = (e: React.PointerEvent<HTMLDivElement>) => {
    if (e.currentTarget.hasPointerCapture(e.pointerId))
      setHeight(
        Math.min(
          window.innerHeight - 170,
          Math.max(300, window.innerHeight - e.clientY),
        ),
      );
  };
  if (!instrument) return null;
  const watched = isInWatchlist(instrument.symbol);
  const watchItem = {
    symbol: instrument.symbol,
    instrumentType: instrument.instrumentType,
    underlyingSymbol: instrument.underlyingSymbol,
  };
  const watch = () => {
    if (watched) {
      removeFromWatchlist(instrument.symbol);
      setUndo(() => () => {
        const result = addCurrent.current(watchItem);
        if (!result.success)
          setNote(result.reason ?? "Could not restore this instrument.");
      });
      return;
    }
    const check = canAdd(watchItem);
    if (!check.allowed) {
      setNote(check.reason ?? "This instrument cannot be added right now.");
      return;
    }
    const result = addToWatchlist(watchItem);
    setNote(
      result.success
        ? null
        : (result.reason ?? "Could not add this instrument."),
    );
  };
  const moneyness = live ? cw?.moneynessCategory : an?.moneynessCategory;
  return (
    <section
      className={`instrument-panel ${expanded ? "is-expanded" : ""}`}
      aria-label={`${instrument.symbol} detail`}
      style={{
        height: expanded ? undefined : `min(${height}px, calc(100dvh - 170px))`,
      }}
    >
      <div
        role="separator"
        aria-label="Resize instrument panel"
        aria-orientation="horizontal"
        aria-valuemin={300}
        aria-valuemax={680}
        aria-valuenow={height}
        tabIndex={0}
        className="panel-resizer"
        onPointerDown={resize}
        onPointerMove={drag}
        onPointerUp={(e) => e.currentTarget.releasePointerCapture(e.pointerId)}
        onKeyDown={(e) => {
          if (e.key === "ArrowUp" || e.key === "ArrowDown") {
            e.preventDefault();
            setHeight(height + (e.key === "ArrowUp" ? 30 : -30));
          }
        }}
      />
      <div className="instrument-header">
        <div className="instrument-identity">
          <strong className="mono">{instrument.symbol}</strong>
          <span>
            {isCW
              ? `Covered warrant · ${instrument.issuer ?? "—"} · ${instrument.underlyingSymbol ?? "—"}`
              : isIndex
                ? "Index · HOSE"
                : "Equity · HOSE"}
          </span>
        </div>
        <div className="segmented" role="tablist" aria-label="Instrument view">
          <button
            role="tab"
            aria-selected={tab === "overview"}
            className={`btn ${tab === "overview" ? "is-active" : ""}`}
            onClick={() => setTab("overview")}
          >
            Overview
          </button>
          {!isIndex && (
            <button
              role="tab"
              aria-selected={tab === "quant"}
              className={`btn ${tab === "quant" ? "is-active" : ""}`}
              onClick={() => setTab("quant")}
            >
              {isCW ? "Quant" : "Events"}
            </button>
          )}
        </div>
        <div className="actions instrument-actions">
          <button
            className={`btn ${watched ? "is-active" : ""}`}
            onClick={watch}
            title={watched ? "Remove from watchlist" : "Add to watchlist"}
          >
            {watched ? "Watching" : "+ Watch"}
          </button>
          <button
            className="icon-btn"
            aria-label={expanded ? "Restore panel size" : "Expand instrument"}
            onClick={() => setExpanded(!expanded)}
          >
            {expanded ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
          </button>
          <button
            className="icon-btn"
            aria-label="Close instrument"
            onClick={onClose}
          >
            <X size={18} />
          </button>
        </div>
      </div>
      {note && <Notice>{note}</Notice>}
      <div ref={bodyRef} className="instrument-body" role="tabpanel">
        {conflicting && (
          <Notice error>
            Conflicting metadata: effective contract terms disagree across
            sources. Quant analytics are withheld until reconciled.
          </Notice>
        )}
        {tab === "overview" ? (
          <div className="overview-grid">
            <aside className="instrument-summary">
              <div className="primary-price">
                <span className="eyebrow">
                  Last price · {isIndex ? "points" : "VND"}
                </span>
                <strong className="mono" style={{ color: change.color }}>
                  {fmtPrice(q?.lastPrice, instrument.instrumentType)}
                </strong>
                <span className="mono" style={{ color: change.color }}>
                  {fmtSigned(amount, instrument.instrumentType)}{" "}
                  <span className="price-percent">{change.text}</span>
                </span>
              </div>
              <div className={`data-status ${live ? "live" : ""}`}>
                {temporalLabel(state)}
              </div>
              <p className="as-of">{formatAsOf(stamp)}</p>
              <dl className="metrics">
                <Metric
                  label="Reference"
                  value={fmtPrice(q?.referencePrice, instrument.instrumentType)}
                />
                <Metric
                  label="Bid / Ask"
                  value={`${fmtPrice(q?.bidPrice, instrument.instrumentType)} / ${fmtPrice(q?.askPrice, instrument.instrumentType)}`}
                />
                <Metric label="Volume" value={fmtVol(q?.totalVolume)} />
              </dl>
              {isCW && (
                <>
                  <h3 className="eyebrow metric-section">Contract</h3>
                  <dl className="metrics">
                    <Metric
                      label="Strike · VND"
                      value={fmtPrice(instrument.strikePrice)}
                    />
                    <Metric
                      label="Exercise ratio"
                      value={fmtRatio(instrument.exerciseRatio)}
                    />
                    <Metric
                      label="Last trading date"
                      value={instrument.lastTradingDate ?? DASH}
                    />
                    <Metric
                      label="Maturity"
                      value={instrument.maturityDate ?? DASH}
                    />
                    <Metric
                      label="Days to maturity"
                      value={dteDisplay(null, instrument.maturityDate)}
                      help="Calendar days to maturity from today in Vietnam. Last trading date is a separate tradability boundary."
                    />
                  </dl>
                </>
              )}
            </aside>
            <div className="chart-workspace">
              <div className="chart-toolbar">
                <div className="segmented" aria-label="Chart range">
                  {["1M", "3M", "6M", "1Y"].map((r) => (
                    <button
                      className={`btn ${range === r ? "is-active" : ""}`}
                      aria-pressed={range === r}
                      key={r}
                      onClick={() => setRange(r)}
                    >
                      {r}
                    </button>
                  ))}
                </div>
                {isCW && (
                  <select
                    aria-label="Comparison mode"
                    value={mode}
                    onChange={(e) => setMode(e.target.value as CWHistoryMode)}
                  >
                    <option value="CW">Warrant</option>
                    <option value="UNDERLYING">Underlying</option>
                    <option value="BOTH">Both prices</option>
                    <option value="RELATIVE">Relative returns</option>
                  </select>
                )}
                <div className="overlay-controls">
                  {(
                    ["REF", "EMA20", "EMA50", "EMA200"] as TechnicalOverlay[]
                  ).map((o) => (
                    <button
                      className={`btn ${overlays.has(o) ? "is-active" : ""}`}
                      disabled={mode === "RELATIVE"}
                      title={
                        mode === "RELATIVE"
                          ? "Price overlays are available in price comparison modes."
                          : undefined
                      }
                      aria-pressed={overlays.has(o)}
                      key={o}
                      onClick={() =>
                        setOverlays((prev) => {
                          const next = new Set(prev);
                          next.has(o) ? next.delete(o) : next.add(o);
                          return next;
                        })
                      }
                    >
                      {o}
                    </button>
                  ))}
                </div>
              </div>
              <div className="chart-canvas">
                {history.isLoading ? (
                  <EmptyState title="Loading daily history…" />
                ) : history.isError ? (
                  <EmptyState
                    title="Could not load price history"
                    action={
                      <button className="btn" onClick={history.refetch}>
                        Retry
                      </button>
                    }
                  />
                ) : !bars.length ? (
                  <EmptyState title="No daily history available" />
                ) : isCW && mode !== "CW" && underlying.isLoading ? (
                  <EmptyState title="Loading underlying history…" />
                ) : isCW &&
                  mode !== "CW" &&
                  (underlying.isError || !underlyingBars.length) ? (
                  <EmptyState
                    title="Underlying history unavailable"
                    action={
                      <button className="btn" onClick={() => setMode("CW")}>
                        Show warrant
                      </button>
                    }
                  />
                ) : (
                  <TradingChart
                    instrumentType={instrument.instrumentType}
                    symbol={instrument.symbol}
                    isCW={isCW}
                    underlyingSymbol={instrument.underlyingSymbol}
                    bars={bars}
                    underlyingBars={mode !== "CW" ? underlyingBars : undefined}
                    liveQuote={live ? q : null}
                    interval="1D"
                    range={range as "1M" | "3M" | "6M" | "1Y"}
                    mode={mode}
                    overlays={overlays}
                    referencePrice={
                      mode === "UNDERLYING"
                        ? (underlyingQuote?.referencePrice ??
                          underlyingBars[underlyingBars.length - 1]
                            ?.referencePrice)
                        : q?.referencePrice
                    }
                    underlyingLiveQuote={live ? underlyingQuote : null}
                    height={chartHeight}
                  />
                )}
              </div>
              <p className="capability-note">
                Daily history ·{" "}
                {isCW ? "Unadjusted warrant prices" : "Adjusted prices"}. Trade
                prints and full order-book depth are not available.
              </p>
            </div>
          </div>
        ) : isCW ? (
          <>
            <div className="quant-heading">
              <span className="data-status">
                {withheld
                  ? "Analytics withheld"
                  : !an && !cw?.analyticsCalculatedAt
                    ? "Analytics unavailable"
                    : live
                      ? "Live analytics"
                      : "Last available analytics"}
              </span>
              <span className="as-of">{formatAsOf(analyticsStamp)}</span>
            </div>
            {withheld && !conflicting && (
              <Notice>
                {an?.unavailableReason ??
                  cw?.quantUnavailableReason ??
                  "Analytics unavailable for this instrument."}
              </Notice>
            )}
            <div className="quant-grid">
              <div className="metric-card">
                <h3>Volatility</h3>
                <dl>
                  <Metric
                    label="IV · bid"
                    value={fmtIV(pick("ivBid"))}
                    help="Annualised implied volatility from the bid price."
                  />
                  <Metric
                    label="IV · trade"
                    value={fmtIV(pick("ivTrade"))}
                    help="Annualised implied volatility from the last traded price, at the stated data time."
                  />
                  <Metric label="IV · ask" value={fmtIV(pick("ivAsk"))} />
                  <Metric
                    label="HV22"
                    value={fmtIV(pick("historicalVolatility"))}
                    help="Historical annualised volatility from 22 adjusted underlying trading sessions; it is not implied volatility."
                  />
                </dl>
              </div>
              <div className="metric-card">
                <h3>Valuation</h3>
                <dl>
                  <Metric
                    label="Theoretical price · VND"
                    value={fmtPrice(pick("theoreticalPrice"))}
                    help="Black–Scholes–Merton model value under its stated inputs. This is not a price target."
                  />
                  <Metric
                    label="Moneyness · S/K"
                    value={
                      pick("moneynessRatio") !== null
                        ? `${pick("moneynessRatio")!.toFixed(3)} · ${moneyness ?? DASH}`
                        : DASH
                    }
                    help="Backend-canonical spot/strike ratio and classification."
                  />
                  <Metric
                    label="Model DTE"
                    value={(live ? cw?.modelDte : an?.dte) ?? DASH}
                    help="Days to maturity at the analytics calculation time. Historical analytics retain their original model inputs."
                  />
                </dl>
              </div>
              <div className="metric-card">
                <h3>Greeks · per warrant</h3>
                <dl>
                  <Metric
                    label="Delta"
                    value={greek(pick("delta"))}
                    help="Change in warrant VND per +1 VND in the underlying; exercise-ratio adjusted."
                  />
                  <Metric
                    label="Gamma"
                    value={
                      pick("gamma") === null
                        ? DASH
                        : pick("gamma")!.toExponential(2)
                    }
                  />
                  <Metric
                    label="Theta · VND/day"
                    value={greek(pick("theta"), 2)}
                    help="Time sensitivity per calendar day."
                  />
                  <Metric
                    label="Vega · VND/vol point"
                    value={greek(pick("vega"), 2)}
                    help="Price sensitivity to +1 percentage point of annualised volatility."
                  />
                  <Metric
                    label="Rho · VND/rate point"
                    value={greek(pick("rho"), 2)}
                  />
                </dl>
              </div>
            </div>
            <details className="model-assumptions">
              <summary>Model assumptions & data provenance</summary>
              <p>
                Black–Scholes–Merton · ACT/365 · dividend yield q = 0 for
                dividend-protected covered warrants · values scaled by the
                effective exercise ratio.
              </p>
              <p>
                Greeks volatility source:{" "}
                {an?.greeksVolatilitySource ??
                  cw?.greeksVolatilitySource ??
                  "Unavailable"}
                . Analytics as of {formatAsOf(analyticsStamp)}.
              </p>
              <p>
                Current contract dates appear in Overview. Historical model
                inputs stay tied to the analytics timestamp; missing values are
                shown as —.
              </p>
            </details>
          </>
        ) : (
          <div className="events-workspace">
            <div className="section-toolbar">
              <div>
                <h2 className="section-title">Company events</h2>
                <p className="section-subtitle">
                  Disclosed timing and terms for {instrument.symbol}; timing
                  does not establish causation.
                </p>
              </div>
            </div>
            {events.isLoading ? (
              <EmptyState title="Loading events…" />
            ) : events.isError ? (
              <Notice
                error
                action={
                  <button className="btn" onClick={events.refetch}>
                    Retry
                  </button>
                }
              >
                Corporate events are unavailable.
              </Notice>
            ) : !events.items.length ? (
              <EmptyState title="No corporate events on record" />
            ) : (
              <div className="table-scroll">
                <table className="data-table events-table">
                  <thead>
                    <tr>
                      <th>Event</th>
                      <th>Ex-date</th>
                      <th>Record date</th>
                      <th>Payment date</th>
                      <th>Terms</th>
                      <th>Source</th>
                    </tr>
                  </thead>
                  <tbody>
                    {events.items.map((ev) => (
                      <tr key={ev.id}>
                        <td>
                          {ev.event_label ||
                            ev.action_type.replace(/_/g, " ").toLowerCase()}
                        </td>
                        <td>{ev.ex_date?.slice(0, 10) ?? DASH}</td>
                        <td>{ev.record_date?.slice(0, 10) ?? DASH}</td>
                        <td>{ev.payment_date?.slice(0, 10) ?? DASH}</td>
                        <td>
                          {ev.cash_amount_vnd != null
                            ? `${fmtPrice(ev.cash_amount_vnd)} VND/share`
                            : (ev.ratio_text ??
                              (ev.ratio_pct != null
                                ? `${ev.ratio_pct}%`
                                : DASH))}
                        </td>
                        <td>{ev.source}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <p className="capability-note">
              Financial statements and fundamental ratios are not available.
            </p>
          </div>
        )}
      </div>
      {undo && (
        <UndoNotice
          text={`${instrument.symbol} removed from watchlist`}
          undo={() => {
            undo();
            setUndo(null);
          }}
          dismiss={() => setUndo(null)}
        />
      )}
    </section>
  );
}
