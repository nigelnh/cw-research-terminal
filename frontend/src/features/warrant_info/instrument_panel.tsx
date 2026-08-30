import { useEffect, useMemo, useState } from "react";
import type { SelectedInstrumentView } from "@/data/selected_instrument";
import type { DashboardRow } from "@/data/query/use_dashboard_data";
import type { ResearchContextEnvelope } from "@/data/ai/use_ai_chat";
import { useWatchlist } from "@/data/watchlist";
import { useHistoricalBars } from "@/data/query";
import { TradingChart } from "@/components/common/trading_chart";
import { AiReplBar } from "@/features/ai_assistant/ai_repl_bar";
import { DASH, fmtChg, fmtIV, fmtPrice, fmtRatio, dteDisplay } from "@/components/common/grid_table";

const VN_TZ = "Asia/Ho_Chi_Minh";

interface InstrumentPanelProps {
  instrument: SelectedInstrumentView | null;
  dashRow?: DashboardRow;
  marketSessionActive: boolean;
  context?: ResearchContextEnvelope;
  onClose: () => void;
}

/* ---------------------------------------------------------------- helpers */

function useTick(active: boolean, ms = 1000): number {
  const [t, setT] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const id = window.setInterval(() => setT(Date.now()), ms);
    return () => window.clearInterval(id);
  }, [active, ms]);
  return t;
}

function asOfText(live: boolean, quoteAsOf: string | null | undefined, nowTick: number): string {
  const d = live ? new Date(nowTick) : quoteAsOf ? new Date(quoteAsOf) : null;
  if (!d || Number.isNaN(d.getTime())) return DASH;
  const mon = new Intl.DateTimeFormat("en-US", { timeZone: VN_TZ, month: "short", day: "numeric" }).format(d);
  const time = new Intl.DateTimeFormat("en-GB", {
    timeZone: VN_TZ,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(d);
  return `${mon} at ${time}`;
}

const LABEL: React.CSSProperties = { fontSize: 10, color: "var(--t-46)" };
const MICRO: React.CSSProperties = { fontSize: 9.5, letterSpacing: "0.06em", color: "var(--t-46)", marginBottom: 6 };

function MetricRow({
  label,
  value,
  color = "var(--t-92)",
  size = 13,
  top = false,
}: {
  label: string;
  value: React.ReactNode;
  color?: string;
  size?: number;
  top?: boolean;
}) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        padding: "5px 0",
        ...(top ? { borderTop: "1px solid var(--border-mid)", marginTop: 4, paddingTop: 8 } : null),
      }}
    >
      <span style={LABEL}>{label}</span>
      <span style={{ fontSize: size, color }}>{value}</span>
    </div>
  );
}

function greek(v: number | null | undefined, dp = 2): string {
  if (typeof v !== "number" || Number.isNaN(v)) return DASH;
  return v.toFixed(dp);
}

/* ---------------------------------------------------------------- panel */

export function InstrumentPanel({
  instrument,
  dashRow,
  marketSessionActive,
  context,
  onClose,
}: InstrumentPanelProps) {
  const { isInWatchlist, addToWatchlist, removeFromWatchlist, canAdd } = useWatchlist();
  const [tab, setTab] = useState<"overview" | "quant">("overview");
  const [addNote, setAddNote] = useState<string | null>(null);

  const hasInstrument = !!instrument;
  const isCW = instrument?.instrumentType === "CW";
  const isIndex = instrument?.instrumentType === "INDEX";
  const symbol = instrument?.symbol ?? null;

  useEffect(() => {
    setTab("overview");
    setAddNote(null);
  }, [symbol]);

  const nowTick = useTick(marketSessionActive);

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

  const cw = instrument?.cw;
  const q = instrument?.quote ?? cw?.quote ?? dashRow?.quote;
  const an = dashRow?.analytics ?? null;

  const last = q?.lastPrice ?? null;
  const ref = q?.referencePrice ?? null;
  const pct = typeof q?.priceChangePercent === "number" ? q.priceChangePercent * 100 : null;
  const chg = fmtChg(pct);
  const bidAsk = `${fmtPrice(q?.bidPrice)} · ${fmtPrice(q?.askPrice)}`;

  const trdColor = (() => {
    if (last === null || ref === null) return "var(--t-70)";
    if (last > ref) return "var(--up)";
    if (last < ref) return "var(--down)";
    return "var(--flat)";
  })();

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

  const priceHistory = useMemo(() => {
    const rows = bars.bars.filter((b) => typeof b.close === "number");
    return rows
      .slice(-12)
      .map((b, i, arr) => {
        const prev = arr[i - 1];
        const p =
          prev && typeof prev.close === "number" && prev.close !== 0
            ? ((b.close as number) / prev.close - 1) * 100
            : null;
        return { date: b.date.slice(5), close: b.close as number, chg: fmtChg(p) };
      })
      .reverse();
  }, [bars.bars]);

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

  return (
    <section
      style={{
        height: hasInstrument ? "min(460px, 55vh)" : "auto",
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
        {hasInstrument ? (
          <>
            <span className="heading" style={{ fontSize: 13, color: "var(--accent)", fontWeight: 700 }}>
              {instrument!.symbol}
            </span>
            <span style={{ fontSize: 11, color: "var(--t-50)" }}>{kindLine}</span>
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
        ) : (
          <>
            <span className="heading" style={{ fontSize: 13, color: "var(--accent)", fontWeight: 700 }}>
              RESEARCH ASSISTANT
            </span>
            <span style={{ fontSize: 11, color: "var(--t-46)" }}>
              select an instrument to ground the conversation
            </span>
          </>
        )}
      </div>

      {hasInstrument && addNote && (
        <div style={{ padding: "6px 20px 0 20px", fontSize: 10.5, color: "var(--t-55)" }}>{addNote}</div>
      )}

      {/* OVERVIEW */}
      {hasInstrument && tab === "overview" && (
        <div style={{ flex: 1, overflowY: "auto", padding: "14px 20px", display: "flex", gap: 22, minHeight: 0 }}>
          <div className="mono" style={{ width: 220, flexShrink: 0 }}>
            <div style={{ display: "flex", flexDirection: "column", marginBottom: 14 }}>
              <MetricRow label="TRD" value={fmtPrice(last)} color={trdColor} />
              <MetricRow label="CHG%" value={chg.text} color={chg.color} />
              <MetricRow label="BID · ASK" value={bidAsk} color="var(--t-70)" />
              <MetricRow
                label="AS OF"
                value={asOfText(marketSessionActive, context?.quoteAsOf, nowTick)}
                color="var(--t-50)"
                size={11}
              />
            </div>
            {isCW && (
              <div style={{ borderTop: "1px solid var(--border-mid)", paddingTop: 10 }}>
                <MetricRow label="STRIKE" value={fmtPrice(instrument!.strikePrice)} />
                <MetricRow label="RATIO" value={fmtRatio(instrument!.exerciseRatio)} />
                <MetricRow label="MATURITY" value={instrument!.maturityDate ?? DASH} />
                <MetricRow
                  label="DTE"
                  value={dteDisplay(instrument!.lastTradingDate, instrument!.maturityDate, an?.dte)}
                />
              </div>
            )}
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

          <div style={{ flex: 1, minWidth: 0, display: "flex", gap: 16 }}>
            <div
              style={{
                flex: isIndex ? 1 : 1.7,
                minWidth: 0,
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
            {!isIndex && (
              <div className="mono" style={{ flex: 1, minWidth: 240, overflowY: "auto" }}>
                <div style={MICRO}>PRICE HISTORY</div>
                {priceHistory.length === 0 ? (
                  <div style={{ fontSize: 11, color: "var(--t-42)" }}>{DASH}</div>
                ) : (
                  priceHistory.map((p) => (
                    <div
                      key={p.date}
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        padding: "4px 0",
                        fontSize: 11,
                        borderBottom: "1px solid var(--border-row)",
                      }}
                    >
                      <span style={{ color: "var(--t-50)" }}>{p.date}</span>
                      <span style={{ color: "var(--t-85)" }}>{fmtPrice(p.close)}</span>
                      <span style={{ color: p.chg.color }}>{p.chg.text}</span>
                    </div>
                  ))
                )}
              </div>
            )}
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
                  color="var(--accent)"
                  size={12}
                  value={`${fmtIV(pick("ivBid"))} · ${fmtIV(pick("ivTrade"))} · ${fmtIV(pick("ivAsk"))}`}
                />
                <MetricRow label="HV22" color="var(--accent)" size={12} value={fmtIV(pick("historicalVolatility"))} />
                <MetricRow
                  label="MONEYNESS S/K"
                  color="var(--accent)"
                  size={12}
                  value={
                    pick("moneynessRatio") !== null
                      ? `${pick("moneynessRatio")!.toFixed(3)}${moneynessCat ? ` · ${moneynessCat}` : ""}`
                      : DASH
                  }
                />
                <MetricRow label="THEO PRICE" color="var(--accent)" size={12} value={fmtPrice(pick("theoreticalPrice"))} />
                <MetricRow label="DELTA" color="var(--accent)" size={12} value={greek(pick("delta"), 4)} />
                <MetricRow label="GAMMA" color="var(--accent)" size={12} value={greek(pick("gamma"), 6)} />
                <MetricRow label="THETA/DAY" color="var(--accent)" size={12} value={greek(pick("theta"), 2)} />
                <MetricRow
                  label="VEGA·RHO /1%"
                  color="var(--accent)"
                  size={12}
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
                    <div className="mono" style={{ flex: 1, border: "1px solid var(--border)", padding: "8px 12px", overflowY: "auto" }}>
                      <div style={{ fontSize: 9.5, color: "var(--t-42)", marginBottom: 4 }}>TIME &amp; SALES</div>
                      <div style={{ fontSize: 10.5, color: "var(--t-42)" }}>
                        {DASH} live trade feed not yet wired — pending backend support
                      </div>
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
                <div style={MICRO}>FINANCIAL INDICATORS</div>
                {isIndex ? (
                  <div style={{ fontSize: 11, color: "var(--t-42)", padding: "8px 0" }}>
                    No fundamentals — index.
                  </div>
                ) : (
                  <>
                    <MetricRow label="EPS" color="var(--accent)" size={12} value={DASH} />
                    <MetricRow label="PE · PB" color="var(--accent)" size={12} value={`${DASH} · ${DASH}`} />
                    <MetricRow label="ROE" color="var(--accent)" size={12} value={DASH} top />
                    <MetricRow label="ROA" color="var(--accent)" size={12} value={DASH} />
                    <MetricRow label="ROIC" color="var(--accent)" size={12} value={DASH} />
                    <MetricRow label="GROSS MARGIN" color="var(--accent)" size={12} value={DASH} />
                    <MetricRow label="NET MARGIN" color="var(--accent)" size={12} value={DASH} />
                  </>
                )}
              </div>
              <div style={{ flex: 1, minWidth: 0, display: "flex", gap: 12 }}>
                <div style={{ flex: 1.4, minWidth: 0, border: "1px solid var(--border)", display: "flex" }}>
                  {bars.isLoading || bars.bars.length === 0 ? (
                    <div style={{ margin: "auto", fontSize: 11, color: "var(--t-42)" }}>
                      {bars.isLoading ? "loading daily bars…" : "no daily history"}
                    </div>
                  ) : (
                    <TradingChart
                      symbol={instrument!.symbol}
                      bars={bars.bars}
                      liveQuote={marketSessionActive ? q ?? null : null}
                      interval="1D"
                      referencePrice={ref}
                      height={300}
                    />
                  )}
                </div>
                {!isIndex && (
                  <div className="mono" style={{ flex: 1, minWidth: 0, border: "1px solid var(--border)", padding: "8px 12px", overflowY: "auto" }}>
                    <div style={MICRO}>CORP EVENTS</div>
                    <div
                      style={{
                        display: "grid",
                        gridTemplateColumns: "100px 74px 74px 1fr",
                        gap: "4px 8px",
                        fontSize: 9,
                        color: "var(--t-42)",
                        paddingBottom: 4,
                        borderBottom: "1px solid var(--border-mid)",
                      }}
                    >
                      <span>EVENT TYPE</span>
                      <span>EX-DIV</span>
                      <span>ISSUE</span>
                      <span>DESC</span>
                    </div>
                    <div style={{ fontSize: 10.5, color: "var(--t-42)", paddingTop: 8 }}>
                      {DASH} corporate-events feed not yet wired — pending data provider
                    </div>
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      )}

      {hasInstrument && !isCW && tab === "quant" && (
        <div style={{ padding: "0 20px 8px 20px", fontSize: 9.5, color: "var(--t-42)" }} className="mono">
          — fundamentals &amp; corp events: pending data provider
        </div>
      )}

      <AiReplBar context={context} />
    </section>
  );
}
