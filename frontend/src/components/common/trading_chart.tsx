/**
 * Trading-Grade Interactive Financial Chart Component
 * Powered by TradingView Lightweight Charts (lightweight-charts)
 *
 * - Canvas OHLCV candlesticks + synchronized volume sub-pane
 * - Interactive crosshair with a synchronized OHLCV header readout (LAST vs HOVER)
 * - Horizontal reference-price level, technical overlays, CW modes (BOTH / RELATIVE)
 * - Incremental live-quote updates (CurrentBarBuilder)
 *
 * Viewport / update strategy (see the bottom-panel chart QA):
 * - The chart is BUILT WITH its data in one effect, keyed on a coarse signature
 *   (symbol / mode / bar COUNT). Building the series already populated avoids an
 *   empty-series layout pass that can collapse the price scale to zero width.
 * - On first build per symbol the view is framed to the last INITIAL_VISIBLE_BARS
 *   via setVisibleLogicalRange — professional candle density, and the price-scale
 *   autoscale is scoped to recent bars (a warrant that decayed 30x still shows its
 *   last weeks legibly).
 * - A separate tiny effect applies live in-flight ticks with series.update() — no
 *   rebuild, no viewport change — so realtime data and resizes never reset zoom/pan.
 * - fitContent() runs only on the explicit "Fit" button.
 */

import { useEffect, useRef, useState, useMemo, useCallback } from "react";
import {
  createChart,
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  type IChartApi,
  type ISeriesApi,
  ColorType,
  CrosshairMode,
  type CandlestickData,
  type HistogramData,
  type LineData,
  type Time,
} from "lightweight-charts";
import type {
  HistoricalBar,
  UnderlyingClosePoint,
  MarketQuote,
} from "@/domain/models";
import type {
  ChartInterval,
  ChartRange,
  CWHistoryMode,
  TechnicalOverlay,
  OHLCVReadout,
} from "@/domain/historical/types";
import { mergeCompletedBarsWithLiveQuote } from "@/domain/historical/current_bar_builder";
import {
  calculateEMA,
  calculateVWAP,
  calculateNormalizedRelative,
} from "@/domain/historical/technical_overlays";
import { RotateCcw } from "lucide-react";

/** Initial px between bars; the visible-range call below recomputes it to frame N bars. */
const BAR_SPACING = 12;
/** Floor so an aggressive zoom-out still leaves candles legible. */
const MIN_BAR_SPACING = 4;
/** Empty bars kept to the right of the newest candle. */
const RIGHT_OFFSET = 4;
/**
 * Recent bars to frame on first load. Bounding the window (vs. fitting the whole
 * dataset) keeps a professional density AND scopes the price-scale autoscale to
 * recent bars.
 */
const INITIAL_VISIBLE_BARS = 45;

const UP = "#22c55e";
const DOWN = "#ef4444";
const VOL_UP = "rgba(34, 197, 94, 0.4)";
const VOL_DOWN = "rgba(239, 68, 68, 0.4)";

interface Props {
  symbol: string;
  isCW?: boolean;
  instrumentType?: "CW" | "STOCK" | "INDEX";
  underlyingSymbol?: string | null;
  bars: HistoricalBar[];
  underlyingBars?: (HistoricalBar | UnderlyingClosePoint)[] | null;
  liveQuote?: MarketQuote | null;
  underlyingLiveQuote?: MarketQuote | null;
  range?: ChartRange;
  interval?: ChartInterval;
  mode?: CWHistoryMode;
  overlays?: Set<TechnicalOverlay>;
  referencePrice?: number | null;
  height?: number;
  onFitContent?: () => void;
}

export function TradingChart({
  symbol,
  isCW = false,
  instrumentType,
  underlyingSymbol,
  bars,
  underlyingBars,
  liveQuote,
  underlyingLiveQuote,
  range,
  interval = "1D",
  mode = "CW",
  overlays,
  referencePrice,
  height = 360,
}: Props) {
  const chartContainerRef = useRef<HTMLDivElement | null>(null);
  const chartInstanceRef = useRef<IChartApi | null>(null);

  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const bothUndLineRef = useRef<ISeriesApi<"Line"> | null>(null);
  const relativeCwSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const relativeUndSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const overlaySeriesMapRef = useRef<Map<string, ISeriesApi<"Line">>>(
    new Map(),
  );

  // Stable primitive key for the overlay set (the prop is often a fresh Set each render).
  const overlayList = useMemo(() => Array.from(overlays ?? []), [overlays]);
  const overlayKey = overlayList.slice().sort().join(",");

  const effectiveCwBars = useMemo(
    () => mergeCompletedBarsWithLiveQuote(bars, liveQuote, interval),
    [bars, liveQuote, interval],
  );

  const effectiveUndBars = useMemo(() => {
    if (!underlyingBars || underlyingBars.length === 0) return [];
    const normalizedUnd: HistoricalBar[] = underlyingBars.map((b) => {
      if ("open" in b) return b as HistoricalBar;
      return {
        symbol: b.symbol,
        date: b.date,
        open: b.close,
        high: b.close,
        low: b.close,
        close: b.close,
        volume: 0,
      };
    });
    return mergeCompletedBarsWithLiveQuote(
      normalizedUnd,
      underlyingLiveQuote,
      interval,
    );
  }, [underlyingBars, underlyingLiveQuote, interval]);

  // Fresh-every-render mirrors so the build effect (keyed on a coarse signature) can
  // read the current bars without listing the array refs as deps.
  const cwBarsRef = useRef(effectiveCwBars);
  const undBarsRef = useRef(effectiveUndBars);
  cwBarsRef.current = effectiveCwBars;
  undBarsRef.current = effectiveUndBars;

  // Rebuild trigger: structural identity + bar COUNT. A within-bucket live tick keeps
  // the count, so it does NOT rebuild (effect B updates it in place).
  const buildSig = `${range ?? "auto"}|${symbol}|${isCW ? 1 : 0}|${mode}|${effectiveCwBars.length}|${effectiveUndBars.length}`;

  const latestBar = useMemo(() => {
    const target = mode === "UNDERLYING" ? effectiveUndBars : effectiveCwBars;
    return target.length > 0 ? target[target.length - 1] : null;
  }, [mode, effectiveCwBars, effectiveUndBars]);

  const [hoveredReadout, setHoveredReadout] = useState<OHLCVReadout | null>(
    null,
  );
  const isHovering = hoveredReadout !== null;

  const activeReadout = useMemo<OHLCVReadout | null>(() => {
    if (hoveredReadout) return hoveredReadout;
    if (!latestBar) return null;
    const displaySym =
      mode === "UNDERLYING" ? underlyingSymbol || symbol : symbol;
    const chg =
      latestBar.open !== null && latestBar.close !== null
        ? latestBar.close - latestBar.open
        : null;
    const chgPct =
      chg !== null && latestBar.open && latestBar.open > 0
        ? chg / latestBar.open
        : null;
    return {
      symbol: displaySym,
      interval,
      timestamp: latestBar.date,
      open: latestBar.open,
      high: latestBar.high,
      low: latestBar.low,
      close: latestBar.close,
      volume: latestBar.volume,
      change: chg,
      changePercent: chgPct,
    };
  }, [hoveredReadout, latestBar, mode, underlyingSymbol, symbol, interval]);

  const formatVnd = (val: number | null | undefined): string => {
    if (val === null || val === undefined || isNaN(val)) return "—";
    return val.toLocaleString("en-US", {
      maximumFractionDigits: instrumentType === "INDEX" ? 2 : 0,
    });
  };
  const formatVol = (val: number | null | undefined): string => {
    if (val === null || val === undefined || isNaN(val)) return "—";
    if (val >= 1_000_000) return `${(val / 1_000_000).toFixed(2)}M`;
    if (val >= 1_000) return `${(val / 1_000).toFixed(1)}k`;
    return val.toLocaleString("en-US");
  };
  const formatBarDate = (ts: string | null | undefined): string => {
    if (!ts) return "—";
    const s = String(ts);
    if (/^\d{4}-\d{2}-\d{2}/.test(s)) return s.slice(0, 10);
    const n = Number(s);
    if (Number.isFinite(n)) {
      const d = new Date(n > 1e11 ? n : n * 1000);
      if (!Number.isNaN(d.getTime())) return d.toISOString().slice(0, 10);
    }
    return s;
  };

  const toChartTime = useCallback((dateStr: string): Time => {
    if (!dateStr) return 0 as Time;
    if (typeof dateStr === "number") {
      return (dateStr > 1e11 ? Math.floor(dateStr / 1000) : dateStr) as Time;
    }
    if (/^\d{4}-\d{2}-\d{2}$/.test(dateStr)) {
      return Math.floor(Date.parse(`${dateStr}T00:00:00Z`) / 1000) as Time;
    }
    const isoStr = dateStr.includes("T") ? dateStr : dateStr.replace(" ", "T");
    const parsed = Date.parse(
      isoStr.endsWith("Z") || isoStr.includes("+") ? isoStr : `${isoStr}Z`,
    );
    if (!isNaN(parsed)) return Math.floor(parsed / 1000) as Time;
    const fallback = new Date(dateStr).getTime();
    return (isNaN(fallback) ? 0 : Math.floor(fallback / 1000)) as Time;
  }, []);

  const prepareSeriesData = useCallback(
    <T extends { time: Time }>(items: T[]): T[] => {
      const map = new Map<number, T>();
      for (const item of items) {
        const t = Number(item.time) || 0;
        if (t > 0) map.set(t, item);
      }
      return Array.from(map.values()).sort(
        (a, b) => (Number(a.time) || 0) - (Number(b.time) || 0),
      );
    },
    [],
  );

  const candleFrom = useCallback(
    (src: HistoricalBar[]) => {
      const candles: CandlestickData[] = [];
      const volume: HistogramData[] = [];
      for (const b of src) {
        if (
          b.open === null ||
          b.high === null ||
          b.low === null ||
          b.close === null
        )
          continue;
        const time = toChartTime(b.date);
        if (Number(time) <= 0) continue;
        candles.push({
          time,
          open: b.open,
          high: b.high,
          low: b.low,
          close: b.close,
        });
        if (b.volume !== null && b.volume >= 0) {
          volume.push({
            time,
            value: b.volume,
            color: b.close >= b.open ? VOL_UP : VOL_DOWN,
          });
        }
      }
      return {
        candles: prepareSeriesData(candles),
        volume: prepareSeriesData(volume),
      };
    },
    [toChartTime, prepareSeriesData],
  );

  // ------------------------------------------------------------------ Build effect
  useEffect(() => {
    if (!chartContainerRef.current) return;

    if (chartInstanceRef.current) {
      chartInstanceRef.current.remove();
      chartInstanceRef.current = null;
    }
    candleSeriesRef.current = null;
    volumeSeriesRef.current = null;
    bothUndLineRef.current = null;
    relativeCwSeriesRef.current = null;
    relativeUndSeriesRef.current = null;
    overlaySeriesMapRef.current.clear();

    const cwBars = cwBarsRef.current;
    const undBars = undBarsRef.current;

    const chart = createChart(chartContainerRef.current, {
      width: chartContainerRef.current.clientWidth || 640,
      height,
      layout: {
        background: { type: ColorType.Solid, color: "#111418" },
        textColor: "#94a3b8",
        fontSize: 11,
        fontFamily: "'IBM Plex Mono', ui-monospace, monospace",
      },
      grid: {
        vertLines: { color: "rgba(255, 255, 255, 0.04)" },
        horzLines: { color: "rgba(255, 255, 255, 0.04)" },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: {
          color: "rgba(212, 232, 250, 0.4)",
          width: 1,
          style: 3,
          labelBackgroundColor: "#1e293b",
        },
        horzLine: {
          color: "rgba(212, 232, 250, 0.4)",
          width: 1,
          style: 3,
          labelBackgroundColor: "#1e293b",
        },
      },
      rightPriceScale: {
        borderColor: "rgba(255, 255, 255, 0.08)",
        scaleMargins: { top: 0.12, bottom: mode === "RELATIVE" ? 0.1 : 0.25 },
      },
      timeScale: {
        borderColor: "rgba(255, 255, 255, 0.08)",
        timeVisible:
          interval === "1m" ||
          interval === "5m" ||
          interval === "15m" ||
          interval === "30m" ||
          interval === "1h",
        secondsVisible: false,
        barSpacing: BAR_SPACING,
        minBarSpacing: MIN_BAR_SPACING,
        rightOffset: RIGHT_OFFSET,
      },
      handleScroll: {
        mouseWheel: true,
        pressedMouseMove: true,
        horzTouchDrag: true,
        vertTouchDrag: false,
      },
      handleScale: {
        axisPressedMouseMove: true,
        mouseWheel: true,
        pinch: true,
      },
    });
    chartInstanceRef.current = chart;

    const vndPriceFormat = {
      type: "price" as const,
      precision: instrumentType === "INDEX" ? 2 : 0,
      minMove: instrumentType === "INDEX" ? 0.01 : 1,
    };
    let framedLen = 0;

    if (mode === "RELATIVE") {
      const pctFormat = {
        type: "custom" as const,
        formatter: (p: number) => `${p.toFixed(1)}%`,
      };
      const cwLine = chart.addSeries(LineSeries, {
        color: "#60a5fa",
        lineWidth: 2,
        title: symbol,
        priceFormat: pctFormat,
      });
      const undLine = chart.addSeries(LineSeries, {
        color: "#f59e0b",
        lineWidth: 2,
        title: underlyingSymbol || "Underlying",
        priceFormat: pctFormat,
      });
      const rel = calculateNormalizedRelative(cwBars, undBars);
      const cwPts: LineData[] = [];
      const undPts: LineData[] = [];
      for (const pt of rel) {
        const time = toChartTime(pt.time);
        if (pt.cw !== null) cwPts.push({ time, value: pt.cw });
        if (pt.underlying !== null) undPts.push({ time, value: pt.underlying });
      }
      cwLine.setData(prepareSeriesData(cwPts));
      undLine.setData(prepareSeriesData(undPts));
      relativeCwSeriesRef.current = cwLine;
      relativeUndSeriesRef.current = undLine;
      framedLen = Math.max(cwPts.length, undPts.length);
    } else {
      const candle = chart.addSeries(CandlestickSeries, {
        upColor: UP,
        downColor: DOWN,
        borderVisible: false,
        wickUpColor: UP,
        wickDownColor: DOWN,
        priceFormat: vndPriceFormat,
        ...(mode === "BOTH" && isCW ? { priceScaleId: "right" as const } : {}),
      });
      candleSeriesRef.current = candle;

      const src = mode === "UNDERLYING" ? undBars : cwBars;
      const { candles, volume } = candleFrom(src);
      candle.setData(candles);
      framedLen = candles.length;

      if (mode === "BOTH" && isCW) {
        const undLine = chart.addSeries(LineSeries, {
          color: "#f59e0b",
          lineWidth: 2,
          priceScaleId: "undScale",
          title: underlyingSymbol || "Underlying",
        });
        chart
          .priceScale("undScale")
          .applyOptions({ scaleMargins: { top: 0.7, bottom: 0.05 } });
        undLine.setData(
          prepareSeriesData(
            undBars
              .filter((b) => b.close !== null && !isNaN(b.close!))
              .map((b) => ({ time: toChartTime(b.date), value: b.close! })),
          ),
        );
        bothUndLineRef.current = undLine;
      } else {
        const volumeSeries = chart.addSeries(HistogramSeries, {
          priceFormat: { type: "volume" },
          priceScaleId: "volScale",
        });
        chart
          .priceScale("volScale")
          .applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
        volumeSeries.setData(volume);
        volumeSeriesRef.current = volumeSeries;
      }

      if (referencePrice && referencePrice > 0 && overlayList.includes("REF")) {
        candle.createPriceLine({
          price: referencePrice,
          color: "#eab308",
          lineWidth: 1,
          lineStyle: 2,
          axisLabelVisible: true,
          title: "REF",
        });
      }

      const overlaySpecs: {
        id: TechnicalOverlay;
        color: string;
        title: string;
        calc: (b: HistoricalBar[]) => { time: string; value: number }[];
      }[] = [
        {
          id: "EMA20",
          color: "#38bdf8",
          title: "EMA 20",
          calc: (b) => calculateEMA(b, 20),
        },
        {
          id: "EMA50",
          color: "#fb923c",
          title: "EMA 50",
          calc: (b) => calculateEMA(b, 50),
        },
        {
          id: "EMA200",
          color: "#c084fc",
          title: "EMA 200",
          calc: (b) => calculateEMA(b, 200),
        },
        {
          id: "VWAP",
          color: "#2dd4bf",
          title: "VWAP",
          calc: (b) => calculateVWAP(b),
        },
      ];
      for (const spec of overlaySpecs) {
        if (!overlayList.includes(spec.id)) continue;
        const s = chart.addSeries(LineSeries, {
          color: spec.color,
          lineWidth: 1,
          title: spec.title,
        });
        s.setData(
          prepareSeriesData(
            spec
              .calc(src)
              .map((p) => ({ time: toChartTime(p.time), value: p.value })),
          ),
        );
        overlaySeriesMapRef.current.set(spec.id, s);
      }
    }

    // Establish a valid layout over the whole dataset first (guarantees a non-zero
    // price scale), then frame the last N bars for professional density + a
    // recent-scoped autoscale.
    chart.timeScale().fitContent();
    if (!range && framedLen > INITIAL_VISIBLE_BARS) {
      chart.timeScale().setVisibleLogicalRange({
        from: framedLen - INITIAL_VISIBLE_BARS - 0.5,
        to: framedLen - 1 + RIGHT_OFFSET,
      });
    }

    chart.subscribeCrosshairMove((param) => {
      const activeSeries = candleSeriesRef.current;
      if (
        !param ||
        !param.time ||
        !param.seriesData ||
        !activeSeries ||
        !param.seriesData.has(activeSeries)
      ) {
        setHoveredReadout(null);
        return;
      }
      const data = param.seriesData.get(activeSeries) as any;
      if (data && data.open !== undefined) {
        const chg = data.close - data.open;
        setHoveredReadout({
          symbol: mode === "UNDERLYING" ? underlyingSymbol || symbol : symbol,
          interval,
          timestamp: String(param.time),
          open: data.open,
          high: data.high,
          low: data.low,
          close: data.close,
          volume: null,
          change: chg,
          changePercent: data.open > 0 ? chg / data.open : 0,
        });
      }
    });

    const resizeObserver = new ResizeObserver((entries) => {
      if (entries.length > 0 && chartInstanceRef.current) {
        chartInstanceRef.current.applyOptions({
          width: entries[0].contentRect.width,
          height,
        });
      }
    });
    resizeObserver.observe(chartContainerRef.current);

    return () => {
      resizeObserver.disconnect();
      if (chartInstanceRef.current) {
        chartInstanceRef.current.remove();
        chartInstanceRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    buildSig,
    height,
    interval,
    referencePrice,
    overlayKey,
    toChartTime,
    instrumentType,
  ]);

  // ------------------------------------------------------------------ Live-tick effect
  // Apply a within-bucket live update to the last bar only. No rebuild, no viewport
  // change — so realtime data and resizes never reset the user's zoom/pan.
  useEffect(() => {
    if (mode === "RELATIVE" || mode === "BOTH") return;
    const s = candleSeriesRef.current;
    if (!s) return;
    const src = mode === "UNDERLYING" ? effectiveUndBars : effectiveCwBars;
    const b = src[src.length - 1];
    if (
      !b ||
      b.open === null ||
      b.high === null ||
      b.low === null ||
      b.close === null
    )
      return;
    const time = toChartTime(b.date);
    if (Number(time) <= 0) return;
    s.update({ time, open: b.open, high: b.high, low: b.low, close: b.close });
    const v = volumeSeriesRef.current;
    if (v && b.volume !== null && b.volume >= 0) {
      v.update({
        time,
        value: b.volume,
        color: b.close >= b.open ? VOL_UP : VOL_DOWN,
      });
    }
  }, [effectiveCwBars, effectiveUndBars, mode, toChartTime]);

  const handleResetZoom = () =>
    chartInstanceRef.current?.timeScale().fitContent();

  const hasData =
    mode === "UNDERLYING"
      ? effectiveUndBars.length > 0
      : effectiveCwBars.length > 0 ||
        (mode === "RELATIVE" &&
          (effectiveCwBars.length > 0 || effectiveUndBars.length > 0));

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: "8px",
        width: "100%",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "6px 10px",
          backgroundColor: "rgba(255, 255, 255, 0.02)",
          border: "1px solid var(--border)",
          borderRadius: "4px",
          fontSize: "11px",
          lineHeight: "1.4",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "12px",
            flexWrap: "wrap",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
            <span
              style={{ fontWeight: 600, color: "var(--foreground)" }}
              className="tnum"
            >
              {activeReadout ? activeReadout.symbol : symbol}
            </span>
            <span style={{ color: "var(--subtle-foreground)" }}>·</span>
            <span
              className="tnum"
              style={{ color: "var(--primary)", fontWeight: 500 }}
            >
              {interval}
            </span>
            {activeReadout && (
              <>
                <span style={{ color: "var(--subtle-foreground)" }}>·</span>
                <span
                  className="tnum"
                  style={{
                    color: isHovering
                      ? "var(--flat)"
                      : "var(--subtle-foreground)",
                  }}
                >
                  {isHovering ? "HOVER" : "LAST"}{" "}
                  {formatBarDate(activeReadout.timestamp)}
                </span>
              </>
            )}
          </div>

          {activeReadout && activeReadout.close !== null && (
            <div
              style={{ display: "flex", alignItems: "center", gap: "6px" }}
              className="tnum"
            >
              <span
                style={{
                  fontWeight: 600,
                  fontSize: "12px",
                  color: "var(--foreground)",
                }}
              >
                {formatVnd(activeReadout.close)}
              </span>
              {activeReadout.change !== null &&
                activeReadout.changePercent !== null && (
                  <span
                    title="Bar change: close − open"
                    style={{
                      color:
                        activeReadout.change > 0
                          ? "var(--up)"
                          : activeReadout.change < 0
                            ? "var(--down)"
                            : "var(--subtle-foreground)",
                    }}
                  >
                    {activeReadout.change > 0 ? "+" : ""}
                    {formatVnd(activeReadout.change)} (
                    {activeReadout.changePercent > 0 ? "+" : ""}
                    {(activeReadout.changePercent * 100).toFixed(2)}%)
                  </span>
                )}
            </div>
          )}

          {activeReadout && activeReadout.open !== null && (
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: "8px",
                color: "var(--muted-foreground)",
                fontSize: "10.5px",
              }}
              className="tnum"
            >
              <span>
                O{" "}
                <strong style={{ color: "var(--foreground)" }}>
                  {formatVnd(activeReadout.open)}
                </strong>
              </span>
              <span>
                H{" "}
                <strong style={{ color: "var(--foreground)" }}>
                  {formatVnd(activeReadout.high)}
                </strong>
              </span>
              <span>
                L{" "}
                <strong style={{ color: "var(--foreground)" }}>
                  {formatVnd(activeReadout.low)}
                </strong>
              </span>
              <span>
                C{" "}
                <strong style={{ color: "var(--foreground)" }}>
                  {formatVnd(activeReadout.close)}
                </strong>
              </span>
              {activeReadout.volume !== null && activeReadout.volume > 0 && (
                <span>
                  V{" "}
                  <strong style={{ color: "var(--foreground)" }}>
                    {formatVol(activeReadout.volume)}
                  </strong>
                </span>
              )}
            </div>
          )}
        </div>

        <button
          onClick={handleResetZoom}
          className="focus-ring"
          title="Fit visible dataset"
          style={{
            display: "flex",
            alignItems: "center",
            gap: "4px",
            padding: "3px 6px",
            borderRadius: "3px",
            background: "transparent",
            border: "1px solid var(--border)",
            color: "var(--subtle-foreground)",
            cursor: "pointer",
            fontSize: "10px",
          }}
        >
          <RotateCcw size={11} />
          <span>Fit</span>
        </button>
      </div>

      <div
        ref={chartContainerRef}
        style={{
          width: "100%",
          height: `${height}px`,
          position: "relative",
          borderRadius: "4px",
          overflow: "hidden",
          border: "1px solid var(--border)",
          backgroundColor: "#111418",
        }}
      >
        {!hasData && (
          <div
            style={{
              position: "absolute",
              inset: 0,
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              gap: "6px",
              color: "var(--subtle-foreground)",
              fontSize: "12px",
              padding: "20px",
              textAlign: "center",
            }}
          >
            <span>
              No historical trade candles available for this interval.
            </span>
            {isCW && (
              <span
                style={{ fontSize: "11px", color: "var(--muted-foreground)" }}
              >
                Covered Warrants without matching trades do not generate fake
                candles.
              </span>
            )}
          </div>
        )}
      </div>

      {mode === "RELATIVE" && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "4px 8px",
            fontSize: "10.5px",
            color: "var(--subtle-foreground)",
            backgroundColor: "rgba(255, 255, 255, 0.01)",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
            <span style={{ display: "flex", alignItems: "center", gap: "4px" }}>
              <span
                style={{
                  width: "8px",
                  height: "2px",
                  backgroundColor: "#60a5fa",
                }}
              />
              <strong style={{ color: "#60a5fa" }}>{symbol}</strong>
            </span>
            <span style={{ display: "flex", alignItems: "center", gap: "4px" }}>
              <span
                style={{
                  width: "8px",
                  height: "2px",
                  backgroundColor: "#f59e0b",
                }}
              />
              <strong style={{ color: "#f59e0b" }}>
                {underlyingSymbol || "Underlying"}
              </strong>
            </span>
          </div>
          <span>NORMALIZED PERFORMANCE (Base = 100)</span>
        </div>
      )}
    </div>
  );
}
