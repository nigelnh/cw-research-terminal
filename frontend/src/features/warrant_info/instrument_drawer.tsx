import { useState, useEffect } from "react";
import { X, Check, Plus, Layers } from "lucide-react";
import type { CoveredWarrant, MarketQuote, UnderlyingClosePoint } from "@/domain/models";
import { useWatchlist } from "@/data/watchlist";
import { useHistoricalBars } from "@/data/query";
import { useSearchParam } from "@/data/url/use_url_state";
import { Change } from "@/components/common/change";
import { LiquidityDonut } from "@/components/common/liquidity_donut";
import { TradingChart } from "@/components/common/trading_chart";
import type {
  ChartRange,
  ChartInterval,
  CWHistoryMode,
  TechnicalOverlay,
} from "@/domain/historical/types";
import {
  RANGE_INTERVAL_COMPATIBILITY,
  DEFAULT_INTERVAL_FOR_RANGE,
} from "@/domain/historical/types";
import { computeSpread, contractStateLabel, daysUntil } from "@/domain/quant_display";

const RANGES: readonly ChartRange[] = ["1D", "5D", "1M", "3M", "6M", "1Y", "MAX"];
const INTERVALS: readonly ChartInterval[] = ["1m", "5m", "15m", "30m", "1h", "1D", "1W", "1M"];
const isChartRange = (v: string): v is ChartRange => (RANGES as readonly string[]).includes(v);
const isChartInterval = (v: string): v is ChartInterval => (INTERVALS as readonly string[]).includes(v);

interface InstrumentDrawerProps {
  instrument: {
    symbol: string;
    instrumentType: "CW" | "STOCK" | "INDEX";
    underlyingSymbol?: string | null;
    issuer?: string | null;
    strikePrice?: number | null;
    exerciseRatio?: number | null;
    maturityDate?: string | null;
    lastTradingDate?: string | null;
    quote?: MarketQuote;
    cw?: CoveredWarrant;
  } | null;
  onClose: () => void;
}

const formatNumber = (val?: number | null): string => {
  if (val === null || val === undefined || isNaN(val)) return "—";
  return val.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 0 });
};

const formatPct = (val?: number | null): string => {
  if (val === null || val === undefined || isNaN(val)) return "—";
  return `${(val * 100).toFixed(1)}%`;
};

const formatRatio = (val?: number | null): string => {
  if (val === null || val === undefined || isNaN(val)) return "—";
  return `${val}:1`;
};

// DTE = calendar days to the MATURITY date, matching the backend `days_to_expiry`
// (ACT, floored at 0). "Days to last trading" is conveyed separately by the contract state.
const calculateDTE = (_lastTradingDate?: string | null, maturityDate?: string | null): string => {
  const d = daysUntil(maturityDate);
  return d === null ? "—" : `${d}d`;
};

// Spread + spread% use the ONE canonical convention (see domain/quant_display.ts):
// spread = ask - bid ; spreadPct = 100 * spread / mid ; "—" unless bid>0, ask>0, ask>=bid.
const spreadAbsStr = (bid?: number | null, ask?: number | null): string => {
  const { abs } = computeSpread(bid, ask);
  return abs === null ? "—" : formatNumber(abs);
};
const spreadPctStr = (bid?: number | null, ask?: number | null): string => {
  const { pct } = computeSpread(bid, ask);
  return pct === null ? "—" : `${pct.toFixed(2)}%`;
};

function ChartPlaceholder({ children, tone }: { children: React.ReactNode; tone: "muted" | "error" }) {
  return (
    <div
      style={{
        height: "320px",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontSize: "12px",
        color: tone === "error" ? "var(--destructive)" : "var(--subtle-foreground)",
        backgroundColor: "#111418",
        borderRadius: "4px",
        border: "1px solid var(--border)",
      }}
    >
      {children}
    </div>
  );
}

function Row({
  label,
  value,
  accent,
  tone,
}: {
  label: string;
  value: React.ReactNode;
  accent?: boolean;
  tone?: "up" | "down" | "flat";
}) {
  const toneCls =
    tone === "up" ? "text-up" : tone === "down" ? "text-down" : tone === "flat" ? "text-flat" : "";

  return (
    <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", padding: "7px 0" }}>
      <span style={{ fontSize: "12px", color: "var(--muted-foreground)" }}>{label}</span>
      <span
        className={`tnum ${accent ? "text-primary" : "text-foreground"} ${toneCls}`}
        style={{ fontSize: "13px" }}
      >
        {value}
      </span>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section style={{ borderTop: "1px solid var(--border)", padding: "16px 24px" }}>
      <h3 className="col-head" style={{ marginBottom: "8px" }}>
        {title}
      </h3>
      {children}
    </section>
  );
}

export function InstrumentDrawer({ instrument, onClose }: InstrumentDrawerProps) {
  const { isInWatchlist, addToWatchlist, removeFromWatchlist, canAdd } = useWatchlist();
  const [activeTab, setActiveTab] = useState<"overview" | "history" | "quant">("overview");

  // Shareable chart config in the URL: ?range= & ?interval=
  const [rangeParam, setRangeParam] = useSearchParam("range", "1M");
  const [intervalParam, setIntervalParam] = useSearchParam("interval", "1D");
  const chartRange: ChartRange = isChartRange(rangeParam) ? rangeParam : "1M";
  const chartInterval: ChartInterval = isChartInterval(intervalParam) ? intervalParam : "1D";

  // Ephemeral chart UI state
  const [cwMode, setCwMode] = useState<CWHistoryMode>("BOTH");
  const [overlays, setOverlays] = useState<Set<TechnicalOverlay>>(new Set(["REF"]));
  const [showOverlayMenu, setShowOverlayMenu] = useState(false);

  const isCW = Boolean(
    instrument &&
      (instrument.instrumentType === "CW" ||
        !!instrument.cw ||
        !!instrument.strikePrice ||
        instrument.symbol.startsWith("C"))
  );

  // Historical bars: server state owned by TanStack Query. Cache reuse across open/close
  // and symbol re-selection; distinct entries per symbol/range/interval; superseded
  // requests are aborted; no localStorage, no manual race guard.
  const wantHistory = Boolean(instrument) && activeTab === "history";
  const cwHistory = useHistoricalBars({
    symbol: instrument?.symbol,
    timeframe: chartRange,
    interval: chartInterval,
    adjusted: true,
    enabled: wantHistory,
  });
  const undHistory = useHistoricalBars({
    symbol: isCW ? instrument?.underlyingSymbol : null,
    timeframe: chartRange,
    interval: chartInterval,
    adjusted: true,
    enabled: wantHistory && isCW && Boolean(instrument?.underlyingSymbol),
  });

  const cwBars = cwHistory.bars;
  const undBars: UnderlyingClosePoint[] = undHistory.bars.map((b) => ({
    symbol: instrument?.underlyingSymbol || "",
    date: b.date,
    close: b.close,
    rawClose: b.close,
  }));
  const historyLoading = cwHistory.isLoading || undHistory.isLoading;
  const historyError = cwHistory.isError || undHistory.isError;
  const historyEmpty = cwHistory.isEmpty && (!isCW || undHistory.isEmpty || undHistory.bars.length === 0);

  // Handle Range change with sensible interval adjustment
  const handleRangeChange = (newRange: ChartRange) => {
    setRangeParam(newRange, "push");
    const compatible = RANGE_INTERVAL_COMPATIBILITY[newRange];
    if (!compatible.includes(chartInterval)) {
      setIntervalParam(DEFAULT_INTERVAL_FOR_RANGE[newRange], "replace");
    }
  };
  const setChartInterval = (i: ChartInterval) => setIntervalParam(i, "push");

  // Toggle individual technical overlay
  const handleToggleOverlay = (ov: TechnicalOverlay) => {
    setOverlays((prev) => {
      const next = new Set(prev);
      if (next.has(ov)) {
        next.delete(ov);
      } else {
        next.add(ov);
      }
      return next;
    });
  };

  // Escape key handler
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);


  if (!instrument) return null;

  const watched = isInWatchlist(instrument.symbol);
  const q = instrument.quote || instrument.cw?.quote;
  const cw = instrument.cw;

  const lastPrice = q?.lastPrice ?? cw?.quote?.lastPrice;
  const bidPrice = q?.bidPrice ?? cw?.quote?.bidPrice;
  const askPrice = q?.askPrice ?? cw?.quote?.askPrice;
  const chgPct = q?.priceChangePercent ?? cw?.quote?.priceChangePercent;
  const volume = q?.totalVolume ?? cw?.quote?.totalVolume;
  const underlyingPrice = cw?.underlyingPrice ?? null;

  // Moneyness is canonical from the backend quant engine (numeric S/K + ITM/ATM/OTM label).
  // The client never recomputes it - if the quant gate rejected the contract metadata, it
  // stays "—" here just as it does in the quant panel.
  const moneynessLabel =
    typeof cw?.moneynessRatio === "number" && cw?.moneynessCategory
      ? `${cw.moneynessRatio.toFixed(3)} · ${cw.moneynessCategory}`
      : "—";
  const contractStateText = contractStateLabel(cw?.contractState);
  const tradableCaveat =
    cw?.isTradable === false
      ? cw?.contractState === "PENDING_MATURITY"
        ? "This warrant has stopped trading; figures below are last-known, not live."
        : null
      : null;

  const handleToggleWatchlist = () => {
    if (watched) {
      removeFromWatchlist(instrument.symbol);
    } else {
      const res = addToWatchlist({
        symbol: instrument.symbol,
        instrumentType: isCW ? "CW" : "STOCK",
        underlyingSymbol: instrument.underlyingSymbol,
        issuer: instrument.issuer,
        strikePrice: instrument.strikePrice,
        exerciseRatio: instrument.exerciseRatio,
        maturityDate: instrument.maturityDate,
        lastTradingDate: instrument.lastTradingDate,
      });

      if (!res.success && res.reason) {
        alert(res.reason);
      }
    }
  };

  const addCheck = !watched
    ? canAdd({
        symbol: instrument.symbol,
        instrumentType: isCW ? "CW" : "STOCK",
        underlyingSymbol: instrument.underlyingSymbol,
      })
    : null;

  return (
    <>
      {/* Backdrop */}
      <div
        onClick={onClose}
        aria-hidden
        style={{
          position: "fixed",
          inset: 0,
          backgroundColor: "rgba(0, 0, 0, 0.4)",
          backdropFilter: "blur(2px)",
          zIndex: 40,
        }}
      />

      {/* Sliding Aside Drawer */}
      <aside
        role="dialog"
        aria-modal="true"
        aria-labelledby="drawer-instrument-symbol"
        style={{
          position: "fixed",
          top: 0,
          bottom: 0,
          right: 0,
          zIndex: 50,
          width: "560px",
          maxWidth: "94vw",
          overflowY: "auto",
          borderLeft: "1px solid var(--border-strong)",
          backgroundColor: "var(--surface)",
          display: "flex",
          flexDirection: "column",
          boxShadow: "-8px 0 32px rgba(0, 0, 0, 0.6)",
        }}
      >
        {/* Header */}
        <header
          style={{
            padding: "20px 24px",
            display: "flex",
            alignItems: "flex-start",
            justifyContent: "space-between",
            gap: "16px",
          }}
        >
          <div>
            <h2
              id="drawer-instrument-symbol"
              className="tnum text-primary"
              style={{ margin: 0, fontSize: "19px", fontWeight: 500, letterSpacing: "-0.01em" }}
            >
              {instrument.symbol}
            </h2>
            <p style={{ marginTop: "4px", fontSize: "12px", color: "var(--muted-foreground)" }}>
              {isCW ? "Covered Warrant" : "Stock"} · {instrument.issuer || "HOSE"}
            </p>
            {isCW && instrument.underlyingSymbol && (
              <p style={{ fontSize: "12px", color: "var(--subtle-foreground)" }}>
                Underlying {instrument.underlyingSymbol} ·{" "}
                <span className="tnum">{formatNumber(underlyingPrice)}</span>
              </p>
            )}
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <button
              onClick={handleToggleWatchlist}
              className="focus-ring"
              title={watched ? "Remove from dashboard" : "Add to dashboard"}
              aria-label={watched ? "Remove from dashboard" : "Add to dashboard"}
              style={{
                display: "flex",
                alignItems: "center",
                gap: "6px",
                padding: "6px 10px",
                borderRadius: "4px",
                fontSize: "12px",
                fontWeight: 500,
                border: "none",
                cursor: "pointer",
                backgroundColor: watched ? "rgba(212, 232, 250, 0.12)" : "rgba(255, 255, 255, 0.05)",
                color: watched ? "var(--primary)" : "var(--muted-foreground)",
                transition: "all 0.15s ease",
              }}
            >
              {watched ? <Check size={14} strokeWidth={1.5} /> : <Plus size={14} strokeWidth={1.5} />}
              <span>{watched ? "Watching" : "Watch"}</span>
            </button>

            <button
              onClick={onClose}
              className="focus-ring"
              title="Close drawer"
              aria-label="Close modal"
              style={{
                background: "transparent",
                border: "none",
                color: "var(--subtle-foreground)",
                cursor: "pointer",
                padding: "6px",
                display: "flex",
                alignItems: "center",
                borderRadius: "4px",
              }}
            >
              <X size={14} strokeWidth={1.5} />
            </button>
          </div>
        </header>

        {/* Minimal Tab Bar */}
        <nav
          style={{
            display: "flex",
            alignItems: "center",
            gap: "20px",
            padding: "0 24px",
            borderBottom: "1px solid var(--border)",
          }}
        >
          <button
            onClick={() => setActiveTab("overview")}
            className="focus-ring"
            style={{
              position: "relative",
              padding: "10px 0",
              fontSize: "12px",
              fontWeight: 500,
              background: "transparent",
              border: "none",
              cursor: "pointer",
              color: activeTab === "overview" ? "var(--primary)" : "var(--muted-foreground)",
            }}
          >
            Overview
            {activeTab === "overview" && (
              <span
                style={{
                  position: "absolute",
                  left: 0,
                  right: 0,
                  bottom: "-1px",
                  height: "1px",
                  backgroundColor: "var(--primary)",
                }}
                aria-hidden
              />
            )}
          </button>

          <button
            onClick={() => setActiveTab("history")}
            className="focus-ring"
            style={{
              position: "relative",
              padding: "10px 0",
              fontSize: "12px",
              fontWeight: 500,
              background: "transparent",
              border: "none",
              cursor: "pointer",
              color: activeTab === "history" ? "var(--primary)" : "var(--muted-foreground)",
            }}
          >
            History
            {activeTab === "history" && (
              <span
                style={{
                  position: "absolute",
                  left: 0,
                  right: 0,
                  bottom: "-1px",
                  height: "1px",
                  backgroundColor: "var(--primary)",
                }}
                aria-hidden
              />
            )}
          </button>

          {isCW && (
            <button
              onClick={() => setActiveTab("quant")}
              className="focus-ring"
              style={{
                position: "relative",
                padding: "10px 0",
                fontSize: "12px",
                fontWeight: 500,
                background: "transparent",
                border: "none",
                cursor: "pointer",
                color: activeTab === "quant" ? "var(--primary)" : "var(--muted-foreground)",
              }}
            >
              Quant
              {activeTab === "quant" && (
                <span
                  style={{
                    position: "absolute",
                    left: 0,
                    right: 0,
                    bottom: "-1px",
                    height: "1px",
                    backgroundColor: "var(--primary)",
                  }}
                  aria-hidden
                />
              )}
            </button>
          )}
        </nav>

        {/* Tab 1: Overview */}
        {activeTab === "overview" && (
          <div>
            {!watched && addCheck && (
              <div
                style={{
                  margin: "12px 24px 0 24px",
                  padding: "8px 12px",
                  borderRadius: "4px",
                  backgroundColor: "rgba(255, 255, 255, 0.03)",
                  border: "1px solid var(--border)",
                  fontSize: "11px",
                  color: "var(--muted-foreground)",
                }}
              >
                Subscription Impact:{" "}
                {addCheck.additionalSymbols.length === 2 ? (
                  <span>
                    Consumes <strong className="text-primary">2 slots</strong> (+{addCheck.additionalSymbols.join(", ")}).
                  </span>
                ) : (
                  <span>
                    Consumes <strong className="text-primary">1 slot</strong> (+{addCheck.additionalSymbols.join(", ")}).
                  </span>
                )}
              </div>
            )}

            <Section title="Market">
              <Row label="Last" value={formatNumber(lastPrice)} />
              <Row label="Change" value={<Change value={chgPct} />} />
              <Row label="Bid" value={formatNumber(bidPrice)} />
              <Row label="Ask" value={formatNumber(askPrice)} />
              <Row
                label="Spread"
                value={`${spreadAbsStr(bidPrice, askPrice)} · ${spreadPctStr(bidPrice, askPrice)}`}
              />
              <Row label="Volume" value={formatNumber(volume)} />
            </Section>

            {/* CW-Specific Sections */}
            {isCW && (
              <>
                {(!instrument.strikePrice && !cw?.strikePrice || !instrument.exerciseRatio && !cw?.exerciseRatio || !instrument.maturityDate && !cw?.maturityDate) && (
                  <div
                    style={{
                      padding: "8px 12px",
                      backgroundColor: "rgba(255, 255, 255, 0.02)",
                      border: "1px solid var(--border)",
                      borderRadius: "4px",
                      marginBottom: "12px",
                      fontSize: "11px",
                      color: "var(--muted-foreground)",
                      lineHeight: "1.4",
                    }}
                  >
                    <strong style={{ color: "var(--foreground)" }}>Partial Specification:</strong> Strike, Ratio, or Maturity Date are unverified in registry for this warrant. Quantitative pricing and Implied Volatility calculations are unavailable.
                  </div>
                )}

                <Section title="Contract">
                  <Row label="Strike" value={formatNumber(instrument.strikePrice || cw?.strikePrice)} />
                  <Row label="Ratio" value={formatRatio(instrument.exerciseRatio || cw?.exerciseRatio)} />
                  <Row label="Last trading" value={instrument.lastTradingDate || cw?.lastTradingDate || "—"} />
                  <Row label="Maturity" value={instrument.maturityDate || cw?.maturityDate || "—"} />
                  <Row label="DTE (to maturity)" value={calculateDTE(instrument.lastTradingDate, instrument.maturityDate)} />
                  <Row label="State" value={contractStateText} />
                  <Row label="Moneyness (S/K)" value={moneynessLabel} />
                </Section>
                {tradableCaveat && (
                  <div style={{ padding: "0 24px 12px", fontSize: "11px", color: "var(--destructive)" }}>
                    {tradableCaveat}
                  </div>
                )}

                <Section title="Volatility">
                  <Row label="IV bid" value={formatPct(cw?.ivBid)} accent />
                  <Row label="IV trade" value={formatPct(cw?.ivTrade)} accent />
                  <Row label="IV ask" value={formatPct(cw?.ivAsk)} accent />
                </Section>

                <Section title="Microstructure Liquidity">
                  <LiquidityDonut data={null} />
                </Section>
              </>
            )}
          </div>
        )}

        {/* Tab 2: History */}
        {activeTab === "history" && (
          <div style={{ padding: "16px 20px" }}>
            {/* Compact CW Current Market Context Banner */}
            {isCW && (
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  padding: "8px 12px",
                  backgroundColor: "rgba(255, 255, 255, 0.03)",
                  border: "1px solid var(--border)",
                  borderRadius: "4px",
                  marginBottom: "12px",
                  fontSize: "11px",
                  flexWrap: "wrap",
                  gap: "8px",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: "10px", flexWrap: "wrap" }}>
                  <span>
                    <strong style={{ color: "var(--foreground)" }}>{instrument.symbol}</strong> ·{" "}
                    <span style={{ color: "var(--primary)" }}>{chartInterval}</span>
                  </span>
                  <span className="tnum">
                    Last{" "}
                    <strong style={{ color: "var(--foreground)" }}>
                      {lastPrice !== null && lastPrice !== undefined ? `${formatNumber(lastPrice)} ₫` : "—"}
                    </strong>
                  </span>
                  <span className="tnum" style={{ color: "var(--muted-foreground)" }}>
                    Bid <span style={{ color: "var(--foreground)" }}>{formatNumber(bidPrice)}</span> · Ask{" "}
                    <span style={{ color: "var(--foreground)" }}>{formatNumber(askPrice)}</span>
                  </span>
                  <span className="tnum" style={{ color: "var(--subtle-foreground)" }}>
                    Spread {spreadAbsStr(bidPrice, askPrice)} ({spreadPctStr(bidPrice, askPrice)})
                  </span>
                </div>
                {instrument.underlyingSymbol && (
                  <div className="tnum" style={{ color: "var(--primary)", fontWeight: 500 }}>
                    {instrument.underlyingSymbol} {formatNumber(underlyingPrice)} ₫
                  </div>
                )}
              </div>
            )}

            {/* Range, Interval, CW Modes & Overlays Controls */}
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                marginBottom: "12px",
                flexWrap: "wrap",
                gap: "8px",
              }}
            >
              {/* Left: Range and Interval Selectors */}
              <div style={{ display: "flex", alignItems: "center", gap: "6px", flexWrap: "wrap" }}>
                {/* Range Selector */}
                <div style={{ display: "flex", gap: "2px", backgroundColor: "rgba(255, 255, 255, 0.04)", padding: "2px", borderRadius: "4px" }}>
                  {RANGES.map((rg) => (
                    <button
                      key={rg}
                      onClick={() => handleRangeChange(rg)}
                      className="focus-ring"
                      style={{
                        padding: "3px 7px",
                        borderRadius: "3px",
                        fontSize: "10.5px",
                        border: "none",
                        cursor: "pointer",
                        backgroundColor: chartRange === rg ? "var(--primary)" : "transparent",
                        color: chartRange === rg ? "var(--primary-foreground)" : "var(--muted-foreground)",
                        fontWeight: chartRange === rg ? 600 : 400,
                      }}
                    >
                      {rg}
                    </button>
                  ))}
                </div>

                <span style={{ color: "var(--border-strong)", fontSize: "11px" }}>|</span>

                {/* Compatible Interval Selector */}
                <div style={{ display: "flex", gap: "2px", backgroundColor: "rgba(255, 255, 255, 0.04)", padding: "2px", borderRadius: "4px" }}>
                  {RANGE_INTERVAL_COMPATIBILITY[chartRange].map((intv) => (
                    <button
                      key={intv}
                      onClick={() => setChartInterval(intv)}
                      className="focus-ring"
                      style={{
                        padding: "3px 6px",
                        borderRadius: "3px",
                        fontSize: "10.5px",
                        border: "none",
                        cursor: "pointer",
                        backgroundColor: chartInterval === intv ? "rgba(255, 255, 255, 0.15)" : "transparent",
                        color: chartInterval === intv ? "var(--foreground)" : "var(--subtle-foreground)",
                        fontWeight: chartInterval === intv ? 600 : 400,
                      }}
                    >
                      {intv}
                    </button>
                  ))}
                </div>
              </div>

              {/* Right: CW Modes & Overlays */}
              <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                {/* CW Modes */}
                {isCW && instrument.underlyingSymbol && (
                  <div style={{ display: "flex", gap: "2px", backgroundColor: "rgba(255, 255, 255, 0.04)", padding: "2px", borderRadius: "4px" }}>
                    {(["BOTH", "CW", "UNDERLYING", "RELATIVE"] as CWHistoryMode[]).map((m) => (
                      <button
                        key={m}
                        onClick={() => setCwMode(m)}
                        className="focus-ring"
                        style={{
                          padding: "3px 6px",
                          borderRadius: "3px",
                          fontSize: "10px",
                          border: "none",
                          cursor: "pointer",
                          backgroundColor: cwMode === m ? "rgba(255, 255, 255, 0.15)" : "transparent",
                          color: cwMode === m ? "var(--foreground)" : "var(--subtle-foreground)",
                          fontWeight: cwMode === m ? 600 : 400,
                        }}
                      >
                        {m === "BOTH" ? "Both" : m === "CW" ? "CW" : m === "UNDERLYING" ? "Und" : "Rel"}
                      </button>
                    ))}
                  </div>
                )}

                {/* Overlays Menu Toggle */}
                <div style={{ position: "relative" }}>
                  <button
                    onClick={() => setShowOverlayMenu((prev) => !prev)}
                    className="focus-ring"
                    title="Technical Overlays"
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: "4px",
                      padding: "3px 6px",
                      borderRadius: "3px",
                      fontSize: "10.5px",
                      border: "1px solid var(--border)",
                      cursor: "pointer",
                      backgroundColor: overlays.size > 0 ? "rgba(212, 232, 250, 0.08)" : "transparent",
                      color: overlays.size > 0 ? "var(--primary)" : "var(--subtle-foreground)",
                    }}
                  >
                    <Layers size={12} />
                    <span>Overlays</span>
                  </button>

                  {/* Overlays Dropdown Popup */}
                  {showOverlayMenu && (
                    <div
                      style={{
                        position: "absolute",
                        right: 0,
                        top: "100%",
                        marginTop: "4px",
                        zIndex: 60,
                        backgroundColor: "#181b20",
                        border: "1px solid var(--border-strong)",
                        borderRadius: "4px",
                        padding: "6px",
                        display: "flex",
                        flexDirection: "column",
                        gap: "4px",
                        minWidth: "120px",
                        boxShadow: "0 6px 16px rgba(0,0,0,0.6)",
                      }}
                    >
                      {(
                        [
                          { id: "REF", label: "Reference Line" },
                          { id: "EMA20", label: "EMA 20" },
                          { id: "EMA50", label: "EMA 50" },
                          { id: "EMA200", label: "EMA 200" },
                          { id: "VWAP", label: "VWAP" },
                        ] as { id: TechnicalOverlay; label: string }[]
                      ).map((item) => {
                        const checked = overlays.has(item.id);
                        return (
                          <label
                            key={item.id}
                            style={{
                              display: "flex",
                              alignItems: "center",
                              gap: "6px",
                              fontSize: "11px",
                              color: checked ? "var(--foreground)" : "var(--muted-foreground)",
                              cursor: "pointer",
                              padding: "2px 4px",
                            }}
                          >
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={() => handleToggleOverlay(item.id)}
                              style={{ cursor: "pointer" }}
                            />
                            {item.label}
                          </label>
                        );
                      })}
                    </div>
                  )}
                </div>
              </div>
            </div>

            {/* Trading-Grade Interactive Chart - explicit loading / error / empty states */}
            {historyLoading && cwBars.length === 0 ? (
              <ChartPlaceholder tone="muted">Loading historical bars…</ChartPlaceholder>
            ) : historyError && cwBars.length === 0 ? (
              <ChartPlaceholder tone="error">
                Could not load historical data. It will retry automatically.
              </ChartPlaceholder>
            ) : historyEmpty ? (
              <ChartPlaceholder tone="muted">
                No historical bars for this instrument in the selected range.
              </ChartPlaceholder>
            ) : (
              <TradingChart
                symbol={instrument.symbol}
                isCW={isCW}
                underlyingSymbol={instrument.underlyingSymbol}
                bars={cwBars}
                underlyingBars={undBars}
                liveQuote={q}
                underlyingLiveQuote={instrument.cw?.quote}
                range={chartRange}
                interval={chartInterval}
                mode={cwMode}
                overlays={overlays}
                referencePrice={q?.referencePrice}
                height={320}
              />
            )}
          </div>
        )}

        {/* Tab 3: Quant (Covered Warrants Only) */}
        {isCW && activeTab === "quant" && (
          <div>
            <Section title="Implied Volatility">
              <Row label="IV Bid" value={formatPct(cw?.ivBid)} accent />
              <Row label="IV Trade" value={formatPct(cw?.ivTrade)} accent />
              <Row label="IV Ask" value={formatPct(cw?.ivAsk)} accent />
            </Section>

            <Section title="First-Order Greeks">
              <Row label="Delta (Δ)" value={cw?.delta !== undefined && cw?.delta !== null ? cw.delta.toFixed(4) : "—"} />
              <Row label="Gamma (Γ)" value={cw?.gamma !== undefined && cw?.gamma !== null ? cw.gamma.toFixed(6) : "—"} />
              <Row label="Theta (Θ / Day)" value={cw?.theta !== undefined && cw?.theta !== null ? `${cw.theta.toFixed(2)} ₫` : "—"} />
              <Row label="Vega (ν / +1%)" value={cw?.vega !== undefined && cw?.vega !== null ? `${cw.vega.toFixed(2)} ₫` : "—"} />
              <Row label="Rho (ρ / +1%)" value={cw?.rho !== undefined && cw?.rho !== null ? `${cw.rho.toFixed(2)} ₫` : "—"} />
            </Section>

            <Section title="Valuation & Moneyness">
              <Row label="Moneyness (S/K)" value={moneynessLabel} />
              <Row label="Underlying Spot (S)" value={formatNumber(underlyingPrice)} />
              <Row label="Strike (K)" value={formatNumber(instrument.strikePrice || cw?.strikePrice)} />
              <Row label="Historical Volatility (HV₂₂)" value={cw?.historicalVolatility !== undefined && cw?.historicalVolatility !== null ? formatPct(cw.historicalVolatility) : "—"} />
              <Row label="Theoretical Fair Price" value={cw?.theoreticalPrice !== undefined && cw?.theoreticalPrice !== null ? `${formatNumber(cw.theoreticalPrice)} ₫` : "—"} />
              {cw?.modelPriceAtIvMid !== undefined && cw?.modelPriceAtIvMid !== null && (
                <Row label="Model Price @ IV Mid" value={`${formatNumber(cw.modelPriceAtIvMid)} ₫`} />
              )}
            </Section>

            <div style={{ margin: "16px 24px", padding: "12px 14px", borderRadius: "4px", backgroundColor: "rgba(255, 255, 255, 0.03)", border: "1px solid var(--border)", fontSize: "11px", color: "var(--muted-foreground)", lineHeight: "1.6" }}>
              <div style={{ fontSize: "11px", fontWeight: 600, color: "var(--foreground)", marginBottom: "4px" }}>Model Assumptions</div>
              <div>Model: European Call Black-Scholes</div>
              <div>Theo Price: Independent Historical Volatility (HV)</div>
              <div>Model Price @ IV Mid: Repriced market midpoint (not independent Theo)</div>
              <div>Risk-free Rate (r): <span className="tnum">5.0%</span> · Dividend Yield (q): <span className="tnum">0.0%</span></div>
              <div>Day-Count: ACT/365 · Exercise Ratio: <span className="tnum">{formatRatio(instrument.exerciseRatio || cw?.exerciseRatio)}</span></div>
            </div>
          </div>
        )}
      </aside>
    </>
  );
}
