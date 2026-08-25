import { useState, useEffect } from "react";
import { X, Check, Plus } from "lucide-react";
import type { CoveredWarrant, MarketQuote, HistoricalBar, UnderlyingClosePoint } from "@/domain/models";
import { useWatchlist } from "@/data/watchlist";
import { providers } from "@/data/providers";
import { Change } from "../common/change";
import { LiquidityDonut } from "../common/liquidity_donut";
import { CandleChart, type Timeframe } from "../common/candle_chart";

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

const calculateDTE = (lastTradingDate?: string | null, maturityDate?: string | null): string => {
  const target = lastTradingDate || maturityDate;
  if (!target) return "—";
  const targetTime = new Date(target).getTime();
  if (isNaN(targetTime)) return "—";
  const diffDays = Math.ceil((targetTime - Date.now()) / (1000 * 60 * 60 * 24));
  return diffDays >= 0 ? `${diffDays}d` : "Expired";
};

const calculateSpread = (bid?: number | null, ask?: number | null): string => {
  if (bid === null || bid === undefined || ask === null || ask === undefined) return "—";
  const diff = ask - bid;
  return diff >= 0 ? diff.toLocaleString("en-US") : "—";
};

const calculateSpreadPct = (bid?: number | null, ask?: number | null, last?: number | null): string => {
  if (bid === null || bid === undefined || ask === null || ask === undefined || !last) return "—";
  const diff = ask - bid;
  if (diff < 0) return "—";
  return `${((diff / last) * 100).toFixed(1)}%`;
};

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
  const [timeframe, setTimeframe] = useState<Timeframe>("1M");
  const [seriesMode, setSeriesMode] = useState<"cw" | "und" | "both">("both");
  const [cwBars, setCwBars] = useState<HistoricalBar[]>([]);
  const [undBars, setUndBars] = useState<UnderlyingClosePoint[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);

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

  // Load historical bars when History tab is selected
  useEffect(() => {
    if (!instrument || activeTab !== "history") return;

    let mounted = true;
    async function loadHistory() {
      setHistoryLoading(true);
      try {
        const symbol = instrument!.symbol;
        const und = instrument!.underlyingSymbol;

        const now = new Date();
        const days =
          timeframe === "1D"
            ? 1
            : timeframe === "5D"
            ? 5
            : timeframe === "1M"
            ? 30
            : timeframe === "3M"
            ? 90
            : timeframe === "6M"
            ? 180
            : 365;

        const from = new Date(now.getTime() - days * 86400000).toISOString().split("T")[0];
        const to = now.toISOString().split("T")[0];
        const range = { fromDate: from, toDate: to };

        const cwData = await providers.historicalData.getHistoricalWarrantBars(symbol, range);
        let undData: UnderlyingClosePoint[] = [];
        if (und) {
          undData = await providers.historicalData.getUnderlyingCloseHistory(und, range);
        }

        if (mounted) {
          setCwBars(cwData || []);
          setUndBars(undData || []);
          setHistoryLoading(false);
        }
      } catch (err) {
        if (mounted) {
          setCwBars([]);
          setUndBars([]);
          setHistoryLoading(false);
        }
      }
    }

    loadHistory();
    return () => {
      mounted = false;
    };
  }, [instrument, activeTab, timeframe]);

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

  // Moneyness calculation
  const moneynessRatio =
    underlyingPrice && instrument.strikePrice
      ? (underlyingPrice / instrument.strikePrice) * 100
      : null;

  const moneynessLabel = moneynessRatio
    ? `${moneynessRatio.toFixed(1)}% ${moneynessRatio >= 100 ? "ITM" : "OTM"}`
    : "—";

  const handleToggleWatchlist = () => {
    if (watched) {
      removeFromWatchlist(instrument.symbol);
    } else {
      const res = addToWatchlist({
        symbol: instrument.symbol,
        instrumentType: instrument.instrumentType,
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
        instrumentType: instrument.instrumentType,
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
          width: "480px",
          maxWidth: "92vw",
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
              {instrument.instrumentType} · {instrument.issuer || "HOSE"}
            </p>
            {instrument.underlyingSymbol && (
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
              <Row label="change" value={<Change value={chgPct} />} />
              <Row label="Bid" value={formatNumber(bidPrice)} />
              <Row label="Ask" value={formatNumber(askPrice)} />
              <Row
                label="Spread"
                value={`${calculateSpread(bidPrice, askPrice)} · ${calculateSpreadPct(bidPrice, askPrice, lastPrice)}`}
              />
              <Row label="Volume" value={formatNumber(volume)} />
            </Section>

            <Section title="Contract">
              <Row label="Strike" value={formatNumber(instrument.strikePrice || cw?.strikePrice)} />
              <Row label="Ratio" value={formatRatio(instrument.exerciseRatio || cw?.exerciseRatio)} />
              <Row label="Maturity" value={instrument.maturityDate || cw?.maturityDate || "—"} />
              <Row label="DTE" value={calculateDTE(instrument.lastTradingDate, instrument.maturityDate)} />
              <Row label="Moneyness (S/K)" value={moneynessLabel} />
            </Section>

            <Section title="Volatility">
              <Row label="IV bid" value={formatPct(cw?.ivBid)} accent />
              <Row label="IV trade" value={formatPct(cw?.ivTrade)} accent />
              <Row label="IV ask" value={formatPct(cw?.ivAsk)} accent />
            </Section>

            <Section title="Microstructure Liquidity">
              <LiquidityDonut data={null} />
            </Section>
          </div>
        )}

        {/* Tab 2: History */}
        {activeTab === "history" && (
          <div style={{ padding: "16px 24px" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "12px" }}>
              {/* Timeframes */}
              <div style={{ display: "flex", gap: "4px" }}>
                {(["1D", "5D", "1M", "3M", "6M", "1Y"] as Timeframe[]).map((tf) => (
                  <button
                    key={tf}
                    onClick={() => setTimeframe(tf)}
                    className="focus-ring"
                    style={{
                      padding: "3px 8px",
                      borderRadius: "3px",
                      fontSize: "11px",
                      border: "none",
                      cursor: "pointer",
                      backgroundColor: timeframe === tf ? "var(--primary)" : "transparent",
                      color: timeframe === tf ? "var(--primary-foreground)" : "var(--muted-foreground)",
                      fontWeight: timeframe === tf ? 600 : 400,
                    }}
                  >
                    {tf}
                  </button>
                ))}
              </div>

              {/* Series toggles */}
              {instrument.underlyingSymbol && (
                <div style={{ display: "flex", gap: "4px" }}>
                  <button
                    onClick={() => setSeriesMode("both")}
                    className="focus-ring"
                    style={{
                      padding: "3px 6px",
                      borderRadius: "3px",
                      fontSize: "10px",
                      border: "none",
                      cursor: "pointer",
                      backgroundColor: seriesMode === "both" ? "rgba(255, 255, 255, 0.1)" : "transparent",
                      color: seriesMode === "both" ? "var(--foreground)" : "var(--subtle-foreground)",
                    }}
                  >
                    Both
                  </button>
                  <button
                    onClick={() => setSeriesMode("cw")}
                    className="focus-ring"
                    style={{
                      padding: "3px 6px",
                      borderRadius: "3px",
                      fontSize: "10px",
                      border: "none",
                      cursor: "pointer",
                      backgroundColor: seriesMode === "cw" ? "rgba(255, 255, 255, 0.1)" : "transparent",
                      color: seriesMode === "cw" ? "var(--foreground)" : "var(--subtle-foreground)",
                    }}
                  >
                    CW
                  </button>
                </div>
              )}
            </div>

            {historyLoading ? (
              <div style={{ padding: "40px 0", textAlign: "center", fontSize: "12px", color: "var(--subtle-foreground)" }}>
                Loading historical bars...
              </div>
            ) : (
              <CandleChart
                bars={cwBars}
                compare={seriesMode === "both" && undBars.length ? undBars : null}
                compareLabel={instrument.underlyingSymbol || undefined}
                height={220}
              />
            )}
          </div>
        )}

        {/* Tab 3: Quant */}
        {activeTab === "quant" && (
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
              <Row label="Historical Volatility (30D)" value={cw?.historicalVolatility !== undefined && cw?.historicalVolatility !== null ? formatPct(cw.historicalVolatility) : "—"} />
              <Row label="Theoretical Fair Price" value={cw?.theoreticalPrice !== undefined && cw?.theoreticalPrice !== null ? `${formatNumber(cw.theoreticalPrice)} ₫` : "—"} />
              {cw?.modelPriceAtIvMid !== undefined && cw?.modelPriceAtIvMid !== null && (
                <Row label="Model Price @ IV Mid" value={`${formatNumber(cw.modelPriceAtIvMid)} ₫`} />
              )}
            </Section>

            <div className="mt-4 px-3 py-2 rounded bg-card/40 border border-border/40 text-[10px] text-muted-foreground font-mono space-y-1">
              <div className="text-[11px] font-semibold text-foreground/80">Model Assumptions</div>
              <div>Model: European Call Black-Scholes</div>
              <div>Theo Price: Independent Historical Volatility (HV)</div>
              <div>Model Price @ IV Mid: Repriced market midpoint (not independent Theo)</div>
              <div>Risk-free Rate (r): 5.0% | Dividend Yield (q): 0.0%</div>
              <div>Day-Count: ACT/365 | Exercise Ratio: {instrument.exerciseRatio || cw?.exerciseRatio || "—"} CW / 1 Share</div>
            </div>
          </div>
        )}
      </aside>
    </>
  );
}
