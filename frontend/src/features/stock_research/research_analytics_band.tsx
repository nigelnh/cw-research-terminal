import { useMemo } from "react";
import { Bar, Scatter } from "react-chartjs-2";
import type { ChartOptions } from "chart.js";
import { ChartCard, useChartTheme, useSeriesPalette } from "@/components/common/chart_card";
import { useUniverseAnalytics, type UniversePoint } from "@/data/query/use_universe_analytics";

/**
 * The Research page's analytics band: three cross-sectional views of the watchlist's
 * warrants, above the registry table.
 *
 * All three read ONE `useUniverseAnalytics` call — no chart issues its own request. The
 * universe is the user's watchlist (not the full ACTIVE registry), so the charts describe
 * what they actually follow, and the underlying REST reads are already warm from Dashboard.
 */
interface Props {
  symbols: string[];
  selectedSymbol?: string | null;
  onSelectSymbol?: (symbol: string | null) => void;
}

const pct = (v: number | null) => (v == null ? "—" : `${(v * 100).toFixed(1)}%`);
const pp = (v: number | null) => (v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(1)}pp`);

/** Compact "3 Dec 26" style month label for the maturity axis. */
function monthLabel(ym: string): string {
  const [y, m] = ym.split("-");
  const names = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];
  const name = names[Number(m) - 1] ?? m;
  return `${name} ${y.slice(2)}`;
}

export function ResearchAnalyticsBand({ symbols, selectedSymbol = null, onSelectSymbol }: Props) {
  const { points, underlyings, cwCount, isLoading, isError, basis } = useUniverseAnalytics(symbols);
  const theme = useChartTheme();
  const palette = useSeriesPalette(underlyings.length);
  const select = onSelectSymbol ?? (() => {});
  const colorOf = useMemo(() => {
    const m = new Map<string, string>();
    underlyings.forEach((u, i) => m.set(u, palette[i]));
    return (u: string | null) => (u ? (m.get(u) ?? theme.tick) : theme.tick);
  }, [underlyings, palette, theme.tick]);

  const emptyNote = isError
    ? "ANALYTICS UNAVAILABLE"
    : isLoading && points.length === 0
      ? "LOADING…"
      : points.length === 0
        ? cwCount > 0
          ? "NO ANALYTICS FOR THIS SESSION"
          : "NO WARRANTS ON THE WATCHLIST"
        : null;

  return (
    <div className="research-band" role="group" aria-label="Watchlist warrant analytics">
      <SkewCard
        points={points}
        underlyings={underlyings}
        colorOf={colorOf}
        theme={theme}
        empty={emptyNote}
        basis={basis}
        selectedSymbol={selectedSymbol}
        onSelect={select}
      />
      <SpreadCard
        points={points}
        theme={theme}
        empty={emptyNote}
        selectedSymbol={selectedSymbol}
        onSelect={select}
      />
      <MaturityCard
        points={points}
        underlyings={underlyings}
        colorOf={colorOf}
        theme={theme}
        empty={emptyNote}
      />
    </div>
  );
}

type Theme = ReturnType<typeof useChartTheme>;
interface CardShared {
  points: UniversePoint[];
  colorOf: (u: string | null) => string;
  theme: Theme;
  empty: string | null;
}

// ------------------------------------------------------------------ 1. skew
/**
 * IV against moneyness, one series per underlying — the shape of the smile.
 *
 * Each underlying's realized vol is a single number, so it was originally drawn as three
 * dashed lines. At this card's height they sat 6 vol points apart and collapsed into one
 * unreadable band, so the HV figures moved to the legend instead: this card answers "what
 * shape is the skew", and the RICH/CHEAP card beside it answers "how far above realized" —
 * no information is lost, it is just read where it is legible.
 */
function SkewCard({
  points, underlyings, colorOf, theme, empty, basis, selectedSymbol, onSelect,
}: CardShared & {
  underlyings: string[];
  basis: string;
  selectedSymbol: string | null;
  onSelect: (s: string) => void;
}) {
  const plotted = points.filter(p => p.moneyness != null && p.ivMid != null);

  const { data, options, refs } = useMemo(() => {
    const hvRefs: UniversePoint[] = [];
    const xs = plotted.map(p => p.moneyness as number);
    const ys = plotted.map(p => (p.ivMid as number) * 100);
    const loX = xs.length ? Math.min(...xs) : 0.8;
    const hiX = xs.length ? Math.max(...xs) : 1.2;
    const padX = Math.max(0.02, (hiX - loX) * 0.08);
    // Fit Y to the data instead of anchoring at zero — implied vol never approaches 0%, and
    // a 0-100 axis spends half the card on empty space and flattens the smile.
    const loY = ys.length ? Math.min(...ys) : 0;
    const hiY = ys.length ? Math.max(...ys) : 100;
    const padY = Math.max(3, (hiY - loY) * 0.12);

    const datasets: any[] = [
      // At-the-money reference: the axis the whole smile is read against.
      {
        label: "__atm",
        data: [{ x: 1, y: loY - padY }, { x: 1, y: hiY + padY }],
        borderColor: theme.tick,
        borderDash: [3, 3],
        borderWidth: 1,
        pointRadius: 0,
        showLine: true,
        fill: false,
        order: 20,
      },
    ];
    for (const u of underlyings) {
      const mine = plotted.filter(p => p.underlying === u);
      if (!mine.length) continue;
      if (mine.some(p => p.hv != null)) hvRefs.push(mine.find(p => p.hv != null) as UniversePoint);
      const color = colorOf(u);
      datasets.push({
        label: u,
        data: mine.map(p => ({ x: p.moneyness, y: (p.ivMid as number) * 100, sym: p.symbol })),
        backgroundColor: color,
        borderColor: theme.panel,
        pointRadius: mine.map(p => (p.symbol === selectedSymbol ? 6 : 3.5)),
        pointHoverRadius: 6,
        pointBorderWidth: mine.map(p => (p.symbol === selectedSymbol ? 1.5 : 0)),
        pointBorderColor: theme.ink,
        order: 1,
      });
    }

    const opts: ChartOptions<"scatter"> = {
      animation: false,
      maintainAspectRatio: false,
      responsive: true,
      layout: { padding: { top: 4, right: 6, bottom: 0, left: 0 } },
      onClick: (_e, els, chart) => {
        const el = els[0];
        if (!el) return;
        const raw: any = chart.data.datasets[el.datasetIndex]?.data?.[el.index];
        if (raw?.sym) onSelect(raw.sym);
      },
      scales: {
        x: {
          type: "linear",
          min: loX - padX,
          max: hiX + padX,
          grid: { color: theme.grid, drawTicks: false },
          border: { color: theme.grid },
          ticks: { color: theme.tick, font: { size: 9 }, padding: 3, maxTicksLimit: 5,
            callback: v => Number(v).toFixed(2) },
        },
        y: {
          min: loY - padY,
          max: hiY + padY,
          grid: { color: theme.grid, drawTicks: false },
          border: { color: theme.grid },
          ticks: { color: theme.tick, font: { size: 9 }, padding: 3, maxTicksLimit: 4,
            callback: v => `${Number(v).toFixed(0)}%` },
        },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          ...theme.tooltip,
          filter: item => item.dataset.label !== "__atm",
          callbacks: {
            title: items => String((items[0]?.raw as any)?.sym ?? ""),
            label: item => `S/K ${Number((item.raw as any).x).toFixed(3)} · IV ${Number((item.raw as any).y).toFixed(1)}%`,
          },
        },
      },
    };
    return { data: { datasets }, options: opts, refs: hvRefs };
  }, [plotted, underlyings, colorOf, theme, selectedSymbol, onSelect]);

  return (
    <ChartCard
      title="VOLATILITY SKEW"
      meta={`IV vs S/K · ${basis === "LIVE" ? "live" : "last close"}`}
      hint="Implied volatility against moneyness, one colour per underlying. The dashed vertical is at-the-money (S/K = 1.00); each underlying's realized volatility is in the legend, so any point above its own HV is priced richer than the stock has actually moved. Click a point to select it."
      empty={empty ?? (plotted.length === 0 ? "NO MONEYNESS DATA" : null)}
      legend={refs.length > 0 ? refs.map(p => (
        <span key={p.underlying}>
          <i style={{ background: colorOf(p.underlying) }} />
          {p.underlying}
          <em>HV {pct(p.hv)}</em>
        </span>
      )) : undefined}
    >
      <Scatter data={data as never} options={options as never} />
    </ChartCard>
  );
}

// -------------------------------------------------------------- 2. rich/cheap
const EXTREME_N = 5;

/**
 * IV minus realized vol, in percentage points, for the five richest and five cheapest
 * warrants on the watchlist. Red is paying more vol than the stock has delivered; green is
 * paying less. The full ranking belongs in the table's own sortable column.
 */
function SpreadCard({
  points, theme, empty, selectedSymbol, onSelect,
}: Omit<CardShared, "colorOf"> & { selectedSymbol: string | null; onSelect: (s: string) => void }) {
  const ranked = points
    .filter(p => p.spreadPp != null)
    .sort((a, b) => (b.spreadPp as number) - (a.spreadPp as number));

  const shown = useMemo(() => {
    if (ranked.length <= EXTREME_N * 2) return ranked;
    return [...ranked.slice(0, EXTREME_N), ...ranked.slice(-EXTREME_N)];
  }, [ranked]);

  const { data, options } = useMemo(() => {
    const opts: ChartOptions<"bar"> = {
      animation: false,
      maintainAspectRatio: false,
      responsive: true,
      indexAxis: "y",
      layout: { padding: { top: 2, right: 8, bottom: 0, left: 0 } },
      onClick: (_e, els) => {
        const el = els[0];
        if (el) onSelect(shown[el.index].symbol);
      },
      scales: {
        x: {
          grid: { color: theme.grid, drawTicks: false },
          border: { color: theme.grid },
          ticks: { color: theme.tick, font: { size: 9 }, padding: 2, maxTicksLimit: 5,
            callback: v => `${Number(v) > 0 ? "+" : ""}${Number(v).toFixed(0)}` },
        },
        y: {
          grid: { display: false },
          border: { color: theme.grid },
          ticks: {
            color: shown.map(p => (p.symbol === selectedSymbol ? theme.ink : theme.tick)) as never,
            font: { size: 9 },
            padding: 3,
            autoSkip: false,
          },
        },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          ...theme.tooltip,
          callbacks: {
            title: items => shown[items[0].dataIndex].symbol,
            label: item => {
              const p = shown[item.dataIndex];
              return `IV ${pct(p.ivMid)} − HV ${pct(p.hv)} = ${pp(p.spreadPp)}`;
            },
          },
        },
      },
    };
    return {
      data: {
        labels: shown.map(p => p.symbol),
        datasets: [{
          data: shown.map(p => p.spreadPp),
          backgroundColor: shown.map(p => ((p.spreadPp as number) >= 0 ? theme.down : theme.up)),
          borderWidth: 0,
          barThickness: "flex" as const,
          maxBarThickness: 11,
          categoryPercentage: 0.86,
          barPercentage: 0.9,
        }],
      },
      options: opts,
    };
  }, [shown, theme, selectedSymbol, onSelect]);

  const note = ranked.length > EXTREME_N * 2
    ? `top ${EXTREME_N} each way · ${ranked.length} total`
    : `${ranked.length} warrants`;

  return (
    <ChartCard
      title="RICH / CHEAP"
      meta={note}
      hint="Implied volatility minus the underlying's realized volatility, in percentage points. Red = the market is pricing more volatility than the stock has delivered; green = less. Click a bar to select it."
      empty={empty ?? (shown.length === 0 ? "NO VOLATILITY SPREAD" : null)}
      legend={
        <>
          <span><i style={{ background: theme.down }} />richer than realized</span>
          <span><i style={{ background: theme.up }} />cheaper</span>
        </>
      }
    >
      <Bar data={data as never} options={options as never} />
    </ChartCard>
  );
}

// ----------------------------------------------------------- 3. maturity ladder
/**
 * How much of the watchlist expires when, stacked by underlying. Answers "what rolls off
 * next month" without reading 27 maturity dates out of the table.
 */
function MaturityCard({
  points, underlyings, colorOf, theme, empty,
}: CardShared & { underlyings: string[] }) {
  const { data, options, months } = useMemo(() => {
    const months = [...new Set(points.map(p => p.maturityMonth).filter((m): m is string => !!m))].sort();
    const datasets = underlyings.map(u => ({
      label: u,
      data: months.map(m => points.filter(p => p.maturityMonth === m && p.underlying === u).length),
      backgroundColor: colorOf(u),
      borderWidth: 0,
      maxBarThickness: 26,
    }));
    const opts: ChartOptions<"bar"> = {
      animation: false,
      maintainAspectRatio: false,
      responsive: true,
      layout: { padding: { top: 4, right: 4, bottom: 0, left: 0 } },
      scales: {
        x: {
          stacked: true,
          grid: { display: false },
          border: { color: theme.grid },
          ticks: { color: theme.tick, font: { size: 8.5 }, padding: 2, autoSkip: false,
            maxRotation: 0, callback: (_v, i) => monthLabel(months[i] ?? "") },
        },
        y: {
          stacked: true,
          grid: { color: theme.grid, drawTicks: false },
          border: { color: theme.grid },
          ticks: { color: theme.tick, font: { size: 9 }, padding: 3, precision: 0, maxTicksLimit: 4 },
        },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          ...theme.tooltip,
          callbacks: {
            title: items => monthLabel(months[items[0].dataIndex] ?? ""),
            label: item => `${item.dataset.label} · ${item.formattedValue} expiring`,
          },
        },
      },
    };
    return { data: { labels: months, datasets }, options: opts, months };
  }, [points, underlyings, colorOf, theme]);

  return (
    <ChartCard
      title="MATURITY LADDER"
      meta={`${points.length} warrants · ${months.length} months`}
      hint="Warrants expiring per calendar month, stacked by underlying. Shows expiry concentration — where a cluster of contracts rolls off at once."
      empty={empty ?? (months.length === 0 ? "NO MATURITY DATA" : null)}
      legend={underlyings.map(u => (
        <span key={u}><i style={{ background: colorOf(u) }} />{u}</span>
      ))}
    >
      <Bar data={data as never} options={options as never} />
    </ChartCard>
  );
}
