import { useMemo } from "react";
import { Bar } from "react-chartjs-2";
import type { ChartOptions } from "chart.js";
import { useChartTheme, token } from "@/components/common/chart_card";

/** Billion VND. Statements arrive in plain VND, which is unreadable on an axis. */
const BILLION = 1_000_000_000;

export interface QuarterRow {
  period: string;
  revenue: number | null;
  net_profit: number | null;
  ebit: number | null;
  net_margin: number | null;
}

/**
 * Revenue and net profit by quarter.
 *
 * Revenue dwarfs profit by an order of magnitude, so profit gets its own right-hand axis -
 * on a shared scale it would be a flat line against the floor and tell you nothing about
 * the trend that actually matters.
 */
export function QuarterlyResultsChart({
  rows,
  isLoading,
  isError,
}: {
  rows: QuarterRow[];
  isLoading: boolean;
  isError: boolean;
}) {
  const theme = useChartTheme();

  const { data, options } = useMemo(() => {
    const revenue = token("--series-1", "#a0c4e1");
    const profit = token("--series-2", "#d9c26a");
    const axis = (position: "left" | "right", color: string) => ({
      position,
      grid: position === "left"
        ? { color: theme.grid, drawTicks: false }
        : { drawOnChartArea: false },
      border: { color: theme.grid },
      ticks: {
        color,
        font: { size: 9 },
        padding: 4,
        callback: (v: unknown) => `${Math.round(Number(v) / BILLION).toLocaleString("en-US")}`,
      },
    });
    const opts: ChartOptions<"bar"> = {
      animation: false,
      maintainAspectRatio: false,
      responsive: true,
      layout: { padding: { top: 6, right: 4, bottom: 0, left: 0 } },
      scales: {
        x: {
          grid: { display: false },
          border: { color: theme.grid },
          ticks: { color: theme.tick, font: { size: 9 }, maxRotation: 0, autoSkip: false },
        },
        y: axis("left", theme.tick) as never,
        y1: axis("right", theme.tick) as never,
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          ...theme.tooltip,
          callbacks: {
            label: (item) =>
              `${item.dataset.label}: ${(Number(item.raw) / BILLION).toLocaleString("en-US", {
                maximumFractionDigits: 1,
              })} bn`,
          },
        },
      },
    };
    return {
      data: {
        labels: rows.map(r => r.period),
        datasets: [
          {
            label: "Revenue", data: rows.map(r => r.revenue),
            backgroundColor: revenue, borderWidth: 0, yAxisID: "y", maxBarThickness: 26,
          },
          {
            label: "Net profit", data: rows.map(r => r.net_profit),
            backgroundColor: profit, borderWidth: 0, yAxisID: "y1", maxBarThickness: 14,
          },
        ],
      },
      options: opts,
    };
  }, [rows, theme]);

  const empty = isError
    ? "Financial statements unavailable."
    : isLoading
      ? "Loading…"
      : rows.length === 0
        ? "No quarterly statements for this symbol."
        : null;

  return (
    <div className="quarterly-results">
      <div className="quarterly-results-cap mono">
        <span>REVENUE &amp; PROFIT, QUARTERLY (BILLION VND)</span>
        {!empty && (
          <span className="quarterly-results-key">
            <i style={{ background: token("--series-1", "#a0c4e1") }} />Revenue
            <i style={{ background: token("--series-2", "#d9c26a"), marginLeft: 10 }} />Net profit
          </span>
        )}
      </div>
      {empty ? (
        <div className="quarterly-results-empty mono">{empty}</div>
      ) : (
        <div className="quarterly-results-body">
          <Bar data={data as never} options={options as never} />
        </div>
      )}
    </div>
  );
}
