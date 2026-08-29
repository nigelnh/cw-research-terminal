import { useMemo } from "react";
import { X } from "lucide-react";
import type { WatchlistItem } from "@/domain/models";
import { useWatchlist } from "@/data/watchlist";
import { useResearchMarket } from "@/data/use_research_market";
import { useDashboardData } from "@/data/query/use_dashboard_data";
import { asOfLabel, temporalLabel } from "@/domain/temporal";
import { deriveSelectedInstrument } from "@/data/selected_instrument";
import { useInstrumentSpecs } from "@/data/instruments/use_instrument_specs";
import { Change } from "@/components/common/change";
import { InstrumentDrawer } from "@/features/warrant_info/instrument_drawer";

interface PersonalDashboardProps {
  onNavigateToUniverse?: () => void;
  selectedSymbol?: string | null;
  onSelectSymbol?: (symbol: string | null) => void;
}

const H = ({ children, right }: { children: React.ReactNode; right?: boolean }) => (
  <th
    className={`col-head`}
    style={{
      whiteSpace: "nowrap",
      borderBottom: "1px solid var(--border-strong)",
      backgroundColor: "var(--background)",
      padding: "8px 12px",
      fontWeight: 500,
      textAlign: right ? "right" : "left",
    }}
  >
    {children}
  </th>
);

export function PersonalDashboard({
  onNavigateToUniverse,
  selectedSymbol = null,
  onSelectSymbol,
}: PersonalDashboardProps) {
  const { items, removeFromWatchlist, plan } = useWatchlist();
  const { quotes, warrants } = useResearchMarket();
  const { getSpec } = useInstrumentSpecs();

  // After-hours / crash-safe fallback layer. During an active session `getRow` returns the
  // live WS quote; outside trading it returns the last completed session's resolved values
  // with provenance, so the table is populated rather than empty. Realtime-only fields with
  // no legitimate fallback stay "—".
  const allSymbols = useMemo(() => items.map((i) => i.symbol), [items]);
  const { getRow, meta } = useDashboardData(allSymbols);
  const resolvedQuote = (symbol: string) => getRow(symbol)?.quote ?? quotes.get(symbol);

  const setSelectedSymbol = onSelectSymbol ?? (() => {});

  // Contract metadata = canonical backend registry spec; watchlist item = identity only;
  // live quote/analytics = realtime store.
  const selectedWatchlistItem = useMemo(
    () => items.find((i) => i.symbol.toUpperCase() === (selectedSymbol ?? "").toUpperCase()) ?? null,
    [items, selectedSymbol]
  );
  const selectedInstrument = useMemo(
    () =>
      deriveSelectedInstrument(selectedSymbol, {
        instrumentSpec: getSpec(selectedSymbol),
        watchlistItem: selectedWatchlistItem,
        quote: selectedSymbol ? quotes.get(selectedSymbol.toUpperCase()) : undefined,
        cw: selectedSymbol ? warrants.get(selectedSymbol.toUpperCase()) : undefined,
      }),
    [selectedSymbol, selectedWatchlistItem, quotes, warrants, getSpec]
  );

  // Helper formatters with strict — fallback (never 0 for missing data)
  const formatPrice = (val: number | null | undefined): string => {
    if (val === null || val === undefined || isNaN(val)) return "—";
    return val.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 0 });
  };

  const formatVolume = (val: number | null | undefined): string => {
    if (val === null || val === undefined || isNaN(val)) return "—";
    return val.toLocaleString("en-US");
  };

  const formatIV = (val: number | null | undefined): string => {
    if (val === null || val === undefined || isNaN(val)) return "—";
    return `${(val * 100).toFixed(1)}%`;
  };

  // DTE anchored to the VN trading calendar date (not the viewer's local clock). When the
  // backend supplies a computed DTE (analytics group) that value wins.
  const vnTodayIso = new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Ho_Chi_Minh" });
  const calculateDTE = (
    lastTradingDate: string | null | undefined,
    maturityDate: string | null | undefined,
    backendDte?: number | null
  ): string => {
    if (typeof backendDte === "number") return backendDte >= 0 ? `${backendDte}d` : "Expired";
    const target = lastTradingDate || maturityDate;
    if (!target) return "—";
    const t = Date.parse(`${String(target).slice(0, 10)}T00:00:00+07:00`);
    const now = Date.parse(`${vnTodayIso}T00:00:00+07:00`);
    if (isNaN(t) || isNaN(now)) return "—";
    const diffDays = Math.round((t - now) / 86_400_000);
    return diffDays >= 0 ? `${diffDays}d` : "Expired";
  };

  const calculateSpread = (bid: number | null | undefined, ask: number | null | undefined): string => {
    if (bid === null || bid === undefined || ask === null || ask === undefined) return "—";
    const diff = ask - bid;
    return diff >= 0 ? diff.toLocaleString("en-US") : "—";
  };

  const calculateSpreadPct = (
    bid: number | null | undefined,
    ask: number | null | undefined
  ): string => {
    if (bid === null || bid === undefined || ask === null || ask === undefined || isNaN(bid) || isNaN(ask) || bid <= 0) return "—";
    const diff = ask - bid;
    if (diff < 0) return "—";
    return `${((diff / bid) * 100).toFixed(2)}%`;
  };

  // Partition watched items strictly by canonical instrument type
  const isCW = (item: WatchlistItem) =>
    item.instrumentType === "CW" || (item.instrumentType !== "STOCK" && item.symbol.startsWith("C") && item.symbol.length >= 6);

  const stockItems = items.filter((i) => !isCW(i));
  const cwItems = items.filter(isCW);

  return (
    <div>
      <header style={{ marginBottom: "20px" }}>
        <h1 style={{ fontSize: "15px", fontWeight: 500, letterSpacing: "-0.01em", color: "var(--foreground)", margin: 0 }}>
          Dashboard
        </h1>
        <p className="tnum" style={{ marginTop: "4px", fontSize: "12px", color: "var(--muted-foreground)", margin: "4px 0 0 0" }}>
          {items.length} instruments · {plan.symbolCount} slots
          {!meta.marketSessionActive && meta.latestCompletedSession ? (
            <span style={{ marginLeft: "10px", color: "var(--subtle-foreground)" }}>
              · Market closed — showing {asOfLabel({ state: "LAST_SESSION", source: "EOD", sessionDate: meta.latestCompletedSession }) || "last session"} close
            </span>
          ) : meta.marketSessionActive ? (
            <span style={{ marginLeft: "10px", color: "var(--subtle-foreground)" }}>· {temporalLabel("LIVE")}</span>
          ) : null}
        </p>
      </header>

      {/* SECTION 1: STOCKS */}
      {stockItems.length > 0 && (
        <section style={{ marginBottom: "28px" }}>
          <h2 style={{ fontSize: "13px", fontWeight: 600, letterSpacing: "-0.01em", color: "var(--foreground)", margin: "0 0 8px 0" }}>
            Stocks ({stockItems.length})
          </h2>
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", minWidth: "700px", borderCollapse: "collapse" }}>
              <thead>
                <tr>
                  <H>Symbol</H>
                  <H right>Ref</H>
                  <H right>Bid</H>
                  <H right>Ask</H>
                  <H right>Last</H>
                  <H right>Chg</H>
                  <H right>Spread</H>
                  <H right>Spread %</H>
                  <H right>Volume</H>
                  <th style={{ width: "32px", borderBottom: "1px solid var(--border-strong)", backgroundColor: "var(--background)" }} />
                </tr>
              </thead>
              <tbody>
                {stockItems.map((item: WatchlistItem) => {
                  const q = resolvedQuote(item.symbol);
                  const lastPrice = q?.lastPrice;
                  const refPrice = q?.referencePrice;
                  const bidPrice = q?.bidPrice;
                  const askPrice = q?.askPrice;
                  const priceChangePct = q?.priceChangePercent;
                  const totalVolume = q?.totalVolume;
                  const isSelected = selectedSymbol === item.symbol;

                  return (
                    <tr
                      key={item.symbol}
                      onClick={() => setSelectedSymbol(item.symbol)}
                      className={`table-row ${isSelected ? "table-row-selected" : ""}`}
                      style={{
                        height: "38px",
                        cursor: "pointer",
                        borderBottom: "1px solid var(--border)",
                      }}
                    >
                      <td className="tnum text-primary" style={{ padding: "0 12px", fontSize: "13px" }}>
                        {item.symbol}
                      </td>
                      <td className="tnum" style={{ padding: "0 12px", textAlign: "right", fontSize: "12px", color: "var(--muted-foreground)" }}>
                        {formatPrice(refPrice)}
                      </td>
                      <td className="tnum" style={{ padding: "0 12px", textAlign: "right", fontSize: "12px", color: "var(--foreground)" }}>
                        {formatPrice(bidPrice)}
                      </td>
                      <td className="tnum" style={{ padding: "0 12px", textAlign: "right", fontSize: "12px", color: "var(--foreground)" }}>
                        {formatPrice(askPrice)}
                      </td>
                      <td className="tnum" style={{ padding: "0 12px", textAlign: "right", fontSize: "13px", color: "var(--foreground)" }}>
                        {formatPrice(lastPrice)}
                      </td>
                      <td style={{ padding: "0 12px", textAlign: "right", fontSize: "12px" }}>
                        <Change value={priceChangePct} />
                      </td>
                      <td className="tnum" style={{ padding: "0 12px", textAlign: "right", fontSize: "12px", color: "var(--muted-foreground)" }}>
                        {calculateSpread(bidPrice, askPrice)}
                      </td>
                      <td className="tnum" style={{ padding: "0 12px", textAlign: "right", fontSize: "12px", color: "var(--muted-foreground)" }}>
                        {calculateSpreadPct(bidPrice, askPrice)}
                      </td>
                      <td className="tnum" style={{ padding: "0 12px", textAlign: "right", fontSize: "12px", color: "var(--muted-foreground)" }}>
                        {formatVolume(totalVolume)}
                      </td>
                      <td style={{ paddingRight: "8px", textAlign: "right" }}>
                        <button
                          title="Remove from dashboard"
                          aria-label={`Remove ${item.symbol} from dashboard`}
                          onClick={(e) => {
                            e.stopPropagation();
                            removeFromWatchlist(item.symbol);
                            if (selectedSymbol === item.symbol) setSelectedSymbol(null);
                          }}
                          className="focus-ring"
                          style={{
                            background: "transparent",
                            border: "none",
                            color: "var(--subtle-foreground)",
                            cursor: "pointer",
                            padding: "4px",
                            borderRadius: "2px",
                            display: "inline-flex",
                            alignItems: "center",
                            transition: "color 0.15s ease",
                          }}
                          onMouseEnter={(e) => (e.currentTarget.style.color = "var(--destructive)")}
                          onMouseLeave={(e) => (e.currentTarget.style.color = "var(--subtle-foreground)")}
                        >
                          <X size={14} strokeWidth={1.5} />
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* SECTION 2: COVERED WARRANTS */}
      {cwItems.length > 0 && (
        <section style={{ marginBottom: "28px" }}>
          <h2 style={{ fontSize: "13px", fontWeight: 600, letterSpacing: "-0.01em", color: "var(--foreground)", margin: "0 0 8px 0" }}>
            Covered Warrants ({cwItems.length})
          </h2>
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", minWidth: "1180px", borderCollapse: "collapse" }}>
              <thead>
                <tr>
                  <H>Symbol</H>
                  <H>Issuer</H>
                  <H>Underlying</H>
                  <H right>Und. price</H>
                  <H right>Bid</H>
                  <H right>Ask</H>
                  <H right>Last</H>
                  <H right>Chg</H>
                  <H right>Spread</H>
                  <H right>Spread %</H>
                  <H right>Volume</H>
                  <H right>Strike</H>
                  <H right>Ratio</H>
                  <H right>DTE</H>
                  <H right>IV bid</H>
                  <H right>IV trade</H>
                  <H right>IV ask</H>
                  <th style={{ width: "32px", borderBottom: "1px solid var(--border-strong)", backgroundColor: "var(--background)" }} />
                </tr>
              </thead>
              <tbody>
                {cwItems.map((item: WatchlistItem) => {
                  const row = getRow(item.symbol);
                  const q = row?.quote ?? quotes.get(item.symbol);
                  const cw = warrants.get(item.symbol);
                  const fbAnalytics = row?.analytics ?? null;

                  const lastPrice = q?.lastPrice ?? cw?.quote?.lastPrice;
                  const bidPrice = q?.bidPrice ?? cw?.quote?.bidPrice;
                  const askPrice = q?.askPrice ?? cw?.quote?.askPrice;
                  const priceChangePct = q?.priceChangePercent ?? cw?.quote?.priceChangePercent;
                  const totalVolume = q?.totalVolume ?? cw?.quote?.totalVolume;

                  // Canonical contract metadata from the backend registry - NOT the
                  // (possibly stale) persisted watchlist item.
                  const spec = getSpec(item.symbol);
                  const underlyingSymbol =
                    spec?.underlyingSymbol || item.underlyingSymbol || cw?.underlyingSymbol || null;
                  const underlyingPrice =
                    cw?.underlyingPrice ??
                    (underlyingSymbol
                      ? getRow(underlyingSymbol)?.quote?.lastPrice ??
                        quotes.get(underlyingSymbol)?.lastPrice ??
                        null
                      : null);
                  const issuer = spec?.issuer ?? null;
                  const strikePrice = spec?.strikePrice ?? null;
                  const exerciseRatio = spec?.exerciseRatio ?? null;
                  const lastTradingDate = spec?.lastTradingDate ?? null;
                  const maturityDate = spec?.maturityDate ?? null;

                  // Live IV from the realtime analytics stream; else the EOD analytics
                  // group from the fallback resolver (iv_trade only - no EOD order book).
                  const ivAsk = cw?.ivAsk ?? fbAnalytics?.ivAsk ?? null;
                  const ivTrade = cw?.ivTrade ?? fbAnalytics?.ivTrade ?? null;
                  const ivBid = cw?.ivBid ?? fbAnalytics?.ivBid ?? null;

                  const isSelected = selectedSymbol === item.symbol;
                  // "partial" reflects the registry's data_quality; "conflicting" is a distinct
                  // state (terms known but disputed). Until the spec loads, show neither.
                  const isPartial = spec ? spec.dataQuality === "PARTIAL" : false;
                  const isConflicting = spec?.metadataVerification === "CONFLICTING";

                  return (
                    <tr
                      key={item.symbol}
                      onClick={() => setSelectedSymbol(item.symbol)}
                      className={`table-row ${isSelected ? "table-row-selected" : ""}`}
                      style={{
                        height: "38px",
                        cursor: "pointer",
                        borderBottom: "1px solid var(--border)",
                      }}
                    >
                      <td className="tnum text-primary" style={{ padding: "0 12px", fontSize: "13px", whiteSpace: "nowrap" }}>
                        <div style={{ display: "inline-flex", alignItems: "center", gap: "6px" }}>
                          <span>{item.symbol}</span>
                          {isPartial && (
                            <span
                              title="Partial specification in registry. Strike, Ratio, or Maturity Date is missing, so Implied Volatility and Greeks are unavailable."
                              aria-label="Partial contract terms"
                              style={{
                                display: "inline-flex",
                                alignItems: "center",
                                justifyContent: "center",
                                fontSize: "10px",
                                color: "var(--muted-foreground)",
                                backgroundColor: "var(--secondary)",
                                padding: "1px 4px",
                                borderRadius: "2px",
                                cursor: "help",
                                fontWeight: 400,
                              }}
                            >
                              partial
                            </span>
                          )}
                          {isConflicting && (
                            <span
                              title="Contract terms are known but disagree across public sources (e.g. an unresolved corporate-action adjustment). Quant analytics are held back until the effective terms are reconciled. Full provenance is in the instrument detail panel."
                              aria-label="Conflicting contract terms"
                              style={{
                                display: "inline-flex",
                                alignItems: "center",
                                fontSize: "10px",
                                color: "var(--muted-foreground)",
                                backgroundColor: "var(--secondary)",
                                padding: "1px 4px",
                                borderRadius: "2px",
                                cursor: "help",
                                fontWeight: 400,
                              }}
                            >
                              unverified
                            </span>
                          )}
                        </div>
                      </td>
                      <td style={{ padding: "0 12px", fontSize: "12px", color: "var(--muted-foreground)" }}>
                        {issuer || "—"}
                      </td>
                      <td className="tnum" style={{ padding: "0 12px", fontSize: "12px", color: "var(--foreground)" }}>
                        {underlyingSymbol || "—"}
                      </td>
                      <td className="tnum" style={{ padding: "0 12px", textAlign: "right", fontSize: "12px", color: "var(--muted-foreground)" }}>
                        {formatPrice(underlyingPrice)}
                      </td>
                      <td className="tnum" style={{ padding: "0 12px", textAlign: "right", fontSize: "12px", color: "var(--foreground)" }}>
                        {formatPrice(bidPrice)}
                      </td>
                      <td className="tnum" style={{ padding: "0 12px", textAlign: "right", fontSize: "12px", color: "var(--foreground)" }}>
                        {formatPrice(askPrice)}
                      </td>
                      <td className="tnum" style={{ padding: "0 12px", textAlign: "right", fontSize: "13px", color: "var(--foreground)" }}>
                        {formatPrice(lastPrice)}
                      </td>
                      <td style={{ padding: "0 12px", textAlign: "right", fontSize: "12px" }}>
                        <Change value={priceChangePct} />
                      </td>
                      <td className="tnum" style={{ padding: "0 12px", textAlign: "right", fontSize: "12px", color: "var(--muted-foreground)" }}>
                        {calculateSpread(bidPrice, askPrice)}
                      </td>
                      <td className="tnum" style={{ padding: "0 12px", textAlign: "right", fontSize: "12px", color: "var(--muted-foreground)" }}>
                        {calculateSpreadPct(bidPrice, askPrice)}
                      </td>
                      <td className="tnum" style={{ padding: "0 12px", textAlign: "right", fontSize: "12px", color: "var(--muted-foreground)" }}>
                        {formatVolume(totalVolume)}
                      </td>
                      <td className="tnum" style={{ padding: "0 12px", textAlign: "right", fontSize: "12px", color: "var(--muted-foreground)" }}>
                        {formatPrice(strikePrice)}
                      </td>
                      <td className="tnum" style={{ padding: "0 12px", textAlign: "right", fontSize: "12px", color: "var(--muted-foreground)" }}>
                        {typeof exerciseRatio === "number" && !isNaN(exerciseRatio) && exerciseRatio > 0 ? `${exerciseRatio}:1` : "—"}
                      </td>
                      <td className="tnum" style={{ padding: "0 12px", textAlign: "right", fontSize: "12px", color: "var(--subtle-foreground)" }}>
                        {calculateDTE(lastTradingDate, maturityDate, fbAnalytics?.dte)}
                      </td>
                      <td className="tnum" style={{ padding: "0 12px", textAlign: "right", fontSize: "12px", color: "var(--muted-foreground)" }}>
                        {formatIV(ivBid)}
                      </td>
                      <td className="tnum text-primary" style={{ padding: "0 12px", textAlign: "right", fontSize: "12px" }}>
                        {formatIV(ivTrade)}
                      </td>
                      <td className="tnum" style={{ padding: "0 12px", textAlign: "right", fontSize: "12px", color: "var(--muted-foreground)" }}>
                        {formatIV(ivAsk)}
                      </td>
                      <td style={{ paddingRight: "8px", textAlign: "right" }}>
                        <button
                          title="Remove from dashboard"
                          aria-label={`Remove ${item.symbol} from dashboard`}
                          onClick={(e) => {
                            e.stopPropagation();
                            removeFromWatchlist(item.symbol);
                            if (selectedSymbol === item.symbol) setSelectedSymbol(null);
                          }}
                          className="focus-ring"
                          style={{
                            background: "transparent",
                            border: "none",
                            color: "var(--subtle-foreground)",
                            cursor: "pointer",
                            padding: "4px",
                            borderRadius: "2px",
                            display: "inline-flex",
                            alignItems: "center",
                            transition: "color 0.15s ease",
                          }}
                          onMouseEnter={(e) => (e.currentTarget.style.color = "var(--destructive)")}
                          onMouseLeave={(e) => (e.currentTarget.style.color = "var(--subtle-foreground)")}
                        >
                          <X size={14} strokeWidth={1.5} />
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {items.length === 0 && (
        <p style={{ padding: "64px 0", textAlign: "center", fontSize: "12px", color: "var(--subtle-foreground)" }}>
          No instruments watched. Add one from{" "}
          {onNavigateToUniverse ? (
            <button
              onClick={onNavigateToUniverse}
              className="focus-ring text-primary"
              style={{ background: "transparent", border: "none", cursor: "pointer", textDecoration: "underline", font: "inherit" }}
            >
              Research
            </button>
          ) : (
            "Research"
          )}
          .
        </p>
      )}

      {/* Right Drawer */}
      <InstrumentDrawer
        instrument={selectedInstrument}
        onClose={() => setSelectedSymbol(null)}
      />
    </div>
  );
}
