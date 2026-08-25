import { useMemo } from "react";
import type { HistoricalBar, UnderlyingClosePoint } from "@/domain/models";

export type Timeframe = "1D" | "5D" | "1M" | "3M" | "6M" | "1Y";

type Props = {
  bars: HistoricalBar[];
  compare?: UnderlyingClosePoint[] | null;
  compareLabel?: string;
  timeframe?: Timeframe;
  height?: number;
};

const W = 560;
const PAD_L = 6;
const PAD_R = 44;

export function CandleChart({
  bars,
  compare,
  compareLabel,
  height = 190,
}: Props) {
  const volH = 46;
  const gap = 10;
  const priceH = height - volH - gap;

  const validBars = useMemo(() => {
    return (bars || []).filter(
      (b) =>
        b.open !== null &&
        b.high !== null &&
        b.low !== null &&
        b.close !== null &&
        !isNaN(b.open) &&
        !isNaN(b.high) &&
        !isNaN(b.low) &&
        !isNaN(b.close)
    );
  }, [bars]);

  const model = useMemo(() => {
    if (!validBars.length) return null;
    const lo = Math.min(...validBars.map((b) => b.low!));
    const hi = Math.max(...validBars.map((b) => b.high!));
    const pad = (hi - lo) * 0.08 || 1;
    const min = lo - pad;
    const max = hi + pad;
    const innerW = W - PAD_L - PAD_R;
    const slot = innerW / validBars.length;
    const bw = Math.max(1, Math.min(9, slot * 0.62));
    const x = (i: number) => PAD_L + slot * (i + 0.5);
    const y = (p: number) => ((max - p) / (max - min)) * priceH;
    const maxV = Math.max(...validBars.map((b) => b.volume || 0)) || 1;

    // Normalised comparison series (percent change from its own first close)
    let cmp: string | null = null;
    const validCompare = (compare || []).filter((c) => c.close !== null && !isNaN(c.close));
    if (validCompare.length > 1) {
      const base = validCompare[0].close!;
      const rel = validCompare.map((b) => (b.close! / base) - 1);
      const rlo = Math.min(...rel);
      const rhi = Math.max(...rel);
      const span = rhi - rlo || 1;
      cmp = validCompare
        .map((_, i) => {
          const cx = PAD_L + (innerW / validCompare.length) * (i + 0.5);
          const cy = priceH - ((rel[i] - rlo) / span) * priceH * 0.9 - priceH * 0.05;
          return `${i ? "L" : "M"}${cx.toFixed(1)},${cy.toFixed(1)}`;
        })
        .join(" ");
    }

    return { min, max, bw, x, y, maxV, cmp };
  }, [validBars, compare, priceH]);

  if (!model) {
    return (
      <div style={{ padding: "40px 0", textAlign: "center", fontSize: "12px", color: "var(--subtle-foreground)" }}>
        No historical data available.
      </div>
    );
  }

  const { min, max, bw, x, y, maxV, cmp } = model;
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => min + (max - min) * f);

  return (
    <div>
      <svg
        viewBox={`0 0 ${W} ${height}`}
        style={{ width: "100%", height }}
        role="img"
        aria-label="Historical price and volume chart"
      >
        {/* Price Grid */}
        {ticks.map((t, i) => {
          const gy = y(t);
          return (
            <g key={i}>
              <line
                x1={PAD_L}
                x2={W - PAD_R}
                y1={gy}
                y2={gy}
                stroke="var(--border)"
                strokeWidth={0.5}
              />
              <text
                x={W - PAD_R + 6}
                y={gy + 3}
                fill="var(--subtle-foreground)"
                fontSize={8.5}
                fontFamily="var(--font-mono)"
              >
                {Math.round(t).toLocaleString("en-US")}
              </text>
            </g>
          );
        })}

        {/* Candles */}
        {validBars.map((b, i) => {
          const up = b.close! >= b.open!;
          const color = up ? "var(--up)" : "var(--down)";
          const cx = x(i);
          const yo = y(b.open!);
          const yc = y(b.close!);
          const top = Math.min(yo, yc);
          const h = Math.max(1, Math.abs(yc - yo));
          return (
            <g key={b.date || i}>
              <line
                x1={cx}
                x2={cx}
                y1={y(b.high!)}
                y2={y(b.low!)}
                stroke={color}
                strokeWidth={0.7}
                opacity={0.75}
              />
              <rect
                x={cx - bw / 2}
                y={top}
                width={bw}
                height={h}
                fill={up ? "none" : color}
                stroke={color}
                strokeWidth={0.8}
                opacity={0.9}
              />
            </g>
          );
        })}

        {/* Normalised Underlying Comparison Line */}
        {cmp && (
          <path
            d={cmp}
            fill="none"
            stroke="var(--primary)"
            strokeWidth={1}
            opacity={0.7}
          />
        )}

        {/* Volume Bars */}
        {validBars.map((b, i) => {
          const up = b.close! >= b.open!;
          const color = up ? "var(--up)" : "var(--down)";
          const cx = x(i);
          const vh = ((b.volume || 0) / maxV) * volH;
          return (
            <rect
              key={`v-${b.date || i}`}
              x={cx - bw / 2}
              y={height - vh}
              width={bw}
              height={Math.max(1, vh)}
              fill={color}
              opacity={0.35}
            />
          );
        })}
      </svg>
      {compare && compareLabel && (
        <div style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "11px", color: "var(--subtle-foreground)", marginTop: "4px" }}>
          <span style={{ height: "2px", width: "12px", backgroundColor: "var(--primary)", display: "inline-block" }} />
          <span>{compareLabel} (Normalised)</span>
        </div>
      )}
    </div>
  );
}
