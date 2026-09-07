import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  Chart as ChartJS,
  BarElement,
  CategoryScale,
  Legend,
  LineElement,
  LinearScale,
  PointElement,
  Tooltip,
  type ChartOptions,
} from "chart.js";

/**
 * chart.js, registered once and dressed in the Grid Terminal's own language.
 *
 * `lightweight-charts` stays the tool for time series (the panel candle chart); this is for
 * the cross-sectional work it does not do — scatter, ranked bars, categorical stacks.
 * chart.js and react-chartjs-2 were already dependencies with no importer.
 *
 * House rules applied to every chart here: no animation (a dense terminal does not
 * ease numbers into place), mono type at terminal sizes, hairline grids on the panel
 * ground, and tooltips styled as panels rather than chart.js's default rounded bubbles.
 */
ChartJS.register(BarElement, CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Legend);

ChartJS.defaults.animation = false;
ChartJS.defaults.maintainAspectRatio = false;
ChartJS.defaults.font.family =
  '"IBM Plex Mono", ui-monospace, SFMono-Regular, "JetBrains Mono", monospace';
ChartJS.defaults.font.size = 9;

/**
 * Resolves a design token to a concrete color. chart.js paints to a canvas and cannot read
 * `var(--x)`, so the value is looked up from the document once per mount. Falls back to the
 * literal when there is no computed style (SSR, or happy-dom in tests).
 */
export function token(name: string, fallback: string): string {
  // `typeof` guard, not optional chaining: `document?.x` still throws a ReferenceError
  // when the identifier is undeclared, which is the case under renderToStaticMarkup.
  if (typeof document === "undefined" || !document.documentElement) return fallback;
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

/** Per-underlying series colors. Stable by index so a symbol keeps its color across charts. */
export const SERIES_FALLBACKS = ["#a0c4e1", "#d9c26a", "#b39ddb", "#8fc7cf", "#d99a86"];

export function useSeriesPalette(count: number): string[] {
  return useMemo(
    () =>
      Array.from({ length: Math.max(0, count) }, (_, i) =>
        token(`--series-${(i % 5) + 1}`, SERIES_FALLBACKS[i % SERIES_FALLBACKS.length]),
      ),
    [count],
  );
}

/** Shared axis/tooltip styling — spread into each chart's own options. */
export function useChartTheme() {
  // Re-resolved on mount so a token change picks up on the next render pass.
  const [t, setT] = useState(() => readTheme());
  useEffect(() => setT(readTheme()), []);
  return t;
}

function readTheme() {
  const grid = token("--border-row", "#333333");
  // Axis text is data, not chrome — it reads at the same weight as the table columns
  // (the same --t-92 the Dashboard/Research tables use for non-semantic values).
  const tick = token("--t-92", "#ebebeb");
  const label = token("--t-92", "#ebebeb");
  return {
    grid,
    tick,
    label,
    accent: token("--accent", "#a0c4e1"),
    up: token("--up", "#4ec97f"),
    down: token("--down", "#e8635a"),
    panel: token("--panel-2", "#2b2b2b"),
    border: token("--border-strong", "#474747"),
    ink: token("--t-92", "#ebebeb"),
    /** Axis defaults for a compact terminal chart. */
    scale: {
      grid: { color: grid, drawTicks: false },
      border: { color: grid, display: true },
      ticks: { color: tick, font: { size: 9 }, padding: 4 },
    },
    tooltip: {
      backgroundColor: token("--panel-3", "#333333"),
      borderColor: token("--border-strong", "#474747"),
      borderWidth: 1,
      cornerRadius: 2,
      displayColors: false,
      padding: 7,
      titleColor: token("--t-92", "#ebebeb"),
      titleFont: { size: 10, weight: 500 as const },
      bodyColor: token("--t-70", "#b3b3b3"),
      bodyFont: { size: 9.5 },
    },
  };
}

/** Options every chart in the band shares. */
export function baseOptions(): ChartOptions<never> {
  return {
    animation: false,
    maintainAspectRatio: false,
    responsive: true,
  } as ChartOptions<never>;
}

interface ChartCardProps {
  title: string;
  /** Short right-aligned qualifier — units, basis, count. */
  meta?: ReactNode;
  /** Explains what the chart answers; surfaced as the card's tooltip. */
  hint?: string;
  /** Replaces the chart body when there is nothing to plot. */
  empty?: string | null;
  /**
   * Key row, rendered as a SIBLING of the chart body rather than inside it. The canvas is
   * taken out of flow so the body can shrink (see `.chart-card-body > canvas`), so anything
   * passed as `children` alongside it would overlap the chart instead of sitting below.
   */
  legend?: ReactNode;
  children: ReactNode;
}

/**
 * The band's card shell — same visual language as `.index-card`: hairline border, mono
 * caption row, chart filling the remaining height, optional key beneath.
 */
export function ChartCard({ title, meta, hint, empty, legend, children }: ChartCardProps) {
  return (
    <section className="chart-card" aria-label={title} title={hint}>
      <div className="chart-card-cap">
        <span className="heading">{title}</span>
        {meta != null && <span className="chart-card-meta">{meta}</span>}
      </div>
      {empty ? (
        <div className="chart-card-empty">{empty}</div>
      ) : (
        <>
          <div className="chart-card-body">{children}</div>
          {legend != null && <div className="chart-legend">{legend}</div>}
        </>
      )}
    </section>
  );
}
