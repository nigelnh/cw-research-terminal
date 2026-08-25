interface LiquidityData {
  bidVolume: number;
  askVolume: number;
}

const R = 26;
const STROKE = 7;
const C = 2 * Math.PI * R;

const formatNumber = (val?: number | null): string => {
  if (val === null || val === undefined || isNaN(val)) return "—";
  return val.toLocaleString("en-US");
};

export function LiquidityDonut({ data }: { data: LiquidityData | null | undefined }) {
  if (!data || (data.bidVolume + data.askVolume === 0)) {
    return (
      <p style={{ padding: "12px 0", fontSize: "12px", color: "var(--subtle-foreground)" }}>
        Book liquidity not published for this instrument.
      </p>
    );
  }

  const total = data.bidVolume + data.askVolume;
  const bidPct = (data.bidVolume / total) * 100;

  return (
    <div style={{ display: "flex", alignItems: "center", gap: "20px", padding: "4px 0" }}>
      <svg width={72} height={72} viewBox="0 0 72 72" aria-hidden>
        <circle
          cx={36}
          cy={36}
          r={R}
          fill="none"
          stroke="var(--border-strong)"
          strokeWidth={STROKE}
        />
        <circle
          cx={36}
          cy={36}
          r={R}
          fill="none"
          stroke="var(--primary)"
          strokeWidth={STROKE}
          strokeDasharray={`${(bidPct / 100) * C} ${C}`}
          transform="rotate(-90 36 36)"
        />
      </svg>
      <dl style={{ flex: 1, fontSize: "12px" }}>
        <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", padding: "4px 0" }}>
          <dt style={{ display: "flex", alignItems: "center", gap: "8px", color: "var(--muted-foreground)" }}>
            <span
              style={{
                height: "6px",
                width: "6px",
                borderRadius: "50%",
                backgroundColor: "var(--primary)",
              }}
              aria-hidden
            />
            Bid liquidity
          </dt>
          <dd className="tnum" style={{ color: "var(--foreground)" }}>
            {bidPct.toFixed(0)}%{" "}
            <span style={{ color: "var(--subtle-foreground)" }}>· {formatNumber(data.bidVolume)}</span>
          </dd>
        </div>
        <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", padding: "4px 0" }}>
          <dt style={{ display: "flex", alignItems: "center", gap: "8px", color: "var(--muted-foreground)" }}>
            <span
              style={{
                height: "6px",
                width: "6px",
                borderRadius: "50%",
                backgroundColor: "var(--border-strong)",
              }}
              aria-hidden
            />
            Ask liquidity
          </dt>
          <dd className="tnum" style={{ color: "var(--foreground)" }}>
            {(100 - bidPct).toFixed(0)}%{" "}
            <span style={{ color: "var(--subtle-foreground)" }}>· {formatNumber(data.askVolume)}</span>
          </dd>
        </div>
      </dl>
    </div>
  );
}
