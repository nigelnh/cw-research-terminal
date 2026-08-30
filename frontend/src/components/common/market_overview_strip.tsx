import { useResearchMarket } from "@/data/use_research_market";
import { fmtChg } from "@/components/common/grid_table";

/**
 * Market-overview strip shown above the Watchlist and Registry bodies.
 *
 * Faithful to the "Direction C" prototype but honest about data: only indices that
 * currently have a realtime quote (today: VNINDEX, which is in the default watchlist)
 * render live figures. Everything else — the other index quotes and all breadth stats
 * (VOL / VAL / gainers-flat-losers) — has no backend field yet and renders "—".
 * Tracked in docs/design/GRID_TERMINAL_FOLLOWUPS.md.
 */

const CARD_INDICES = ["VNINDEX", "VN30", "HNX30", "HNXINDEX"];
const TABLE_INDICES = ["VNINDEX", "VN30", "HNX30", "VNXALL", "HNXINDEX", "HNXUPCOM"];

const DASH = "—";

function fmtPoint(v: number | null | undefined): string {
  if (typeof v !== "number" || !Number.isFinite(v)) return DASH;
  return v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function MarketOverviewStrip() {
  const { getQuote, marketSessionActive } = useResearchMarket();
  const statusLabel = marketSessionActive ? "Live" : "Closed";

  return (
    <div style={{ display: "flex", gap: 8, marginBottom: 18 }}>
      {CARD_INDICES.map((sym) => {
        const q = getQuote(sym);
        const pct = typeof q?.priceChangePercent === "number" ? q.priceChangePercent * 100 : null;
        const chg = fmtChg(pct);
        return (
          <div
            key={sym}
            style={{ flex: 1, minWidth: 0, border: "1px solid var(--border)", padding: "10px 12px" }}
          >
            <div
              style={{
                height: 64,
                background:
                  "repeating-linear-gradient(135deg, var(--panel) 0px, var(--panel) 8px, oklch(0.14 0 0) 8px, oklch(0.14 0 0) 16px)",
                marginBottom: 8,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <span className="mono" style={{ fontSize: 9.5, color: "var(--t-40)" }}>
                1D
              </span>
            </div>
            <div
              className="mono"
              style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between" }}
            >
              <span style={{ fontSize: 12, color: "var(--accent)", fontWeight: 600 }}>{sym}</span>
              <span style={{ fontSize: 12, color: pct === null ? "var(--t-46)" : chg.color }}>
                {fmtPoint(q?.lastPrice)} {pct === null ? "" : `(${chg.text})`}
              </span>
            </div>
            <div className="mono" style={{ fontSize: 9.5, color: "var(--t-46)", marginTop: 3 }}>
              {DASH} shares · {statusLabel}
            </div>
          </div>
        );
      })}

      <div
        className="mono"
        style={{ flex: 1.6, minWidth: 0, border: "1px solid var(--border)", padding: "8px 12px" }}
      >
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 10.5 }}>
          <thead>
            <tr style={{ borderBottom: "1px solid var(--border-mid)" }}>
              {["INDEX", "POINT", "+/-", "VOL(MIL)", "VAL(BIL)", "G/F/L"].map((h, i) => (
                <th
                  key={h}
                  style={{
                    textAlign: i === 0 ? "left" : "right",
                    padding: "3px 4px",
                    color: "var(--t-46)",
                    fontWeight: 500,
                  }}
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {TABLE_INDICES.map((sym) => {
              const q = getQuote(sym);
              const pct =
                typeof q?.priceChangePercent === "number" ? q.priceChangePercent * 100 : null;
              const chg = fmtChg(pct);
              return (
                <tr key={sym} style={{ borderBottom: "1px solid var(--border-19)" }}>
                  <td style={{ padding: "3px 4px", color: "var(--accent)" }}>{sym}</td>
                  <td style={{ padding: "3px 4px", textAlign: "right" }}>{fmtPoint(q?.lastPrice)}</td>
                  <td
                    style={{
                      padding: "3px 4px",
                      textAlign: "right",
                      color: pct === null ? "var(--t-46)" : chg.color,
                    }}
                  >
                    {chg.text}
                  </td>
                  <td style={{ padding: "3px 4px", textAlign: "right", color: "var(--t-60)" }}>
                    {DASH}
                  </td>
                  <td style={{ padding: "3px 4px", textAlign: "right", color: "var(--t-60)" }}>
                    {DASH}
                  </td>
                  <td style={{ padding: "3px 4px", textAlign: "right", color: "var(--t-46)" }}>
                    {DASH}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
