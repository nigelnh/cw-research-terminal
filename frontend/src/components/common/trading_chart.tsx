/**
 * Trading-Grade Interactive Financial Chart Component
 * Powered by TradingView Lightweight Charts (lightweight-charts)
 *
 * Implements:
 * - Canvas OHLCV Candlestick & Synchronized Volume Sub-Pane
 * - Mouse-wheel / Trackpad horizontal zoom, Drag pan, Fit content
 * - Interactive Crosshair with synchronized OHLCV Header Readout
 * - Horizontal Reference Price level for stocks
 * - Technical Overlays: EMA 20, EMA 50, EMA 200, VWAP
 * - Covered Warrant Modes: CW, Underlying, Both (synchronized dual panes), Relative (Base 100)
 * - Incremental live quote updates (CurrentBarBuilder)
 * - Dark terminal aesthetic conforming to CSS design tokens
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
import type { HistoricalBar, UnderlyingClosePoint, MarketQuote } from "@/domain/models";
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

interface Props {
  symbol: string;
  isCW?: boolean;
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
  underlyingSymbol,
  bars,
  underlyingBars,
  liveQuote,
  underlyingLiveQuote,
  interval = "1D",
  mode = "CW",
  overlays = new Set(),
  referencePrice,
  height = 360,
}: Props) {
  const chartContainerRef = useRef<HTMLDivElement | null>(null);
  const chartInstanceRef = useRef<IChartApi | null>(null);

  // Series references
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const undCandleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const relativeCwSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const relativeUndSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const overlaySeriesMapRef = useRef<Map<string, ISeriesApi<"Line">>>(new Map());

  // Merge completed historical bars with active live candle
  const effectiveCwBars = useMemo(() => {
    return mergeCompletedBarsWithLiveQuote(bars, liveQuote, interval);
  }, [bars, liveQuote, interval]);

  const effectiveUndBars = useMemo(() => {
    if (!underlyingBars || underlyingBars.length === 0) return [];
    // Convert to HistoricalBar if UnderlyingClosePoint
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
    return mergeCompletedBarsWithLiveQuote(normalizedUnd, underlyingLiveQuote, interval);
  }, [underlyingBars, underlyingLiveQuote, interval]);

  // Latest candle for default readout
  const latestBar = useMemo(() => {
    const target = mode === "UNDERLYING" ? effectiveUndBars : effectiveCwBars;
    return target.length > 0 ? target[target.length - 1] : null;
  }, [mode, effectiveCwBars, effectiveUndBars]);

  // Hover state for interactive OHLCV readout
  const [hoveredReadout, setHoveredReadout] = useState<OHLCVReadout | null>(null);

  const activeReadout = useMemo<OHLCVReadout | null>(() => {
    if (hoveredReadout) return hoveredReadout;
    if (!latestBar) return null;

    const displaySym = mode === "UNDERLYING" ? underlyingSymbol || symbol : symbol;
    const chg =
      latestBar.open !== null && latestBar.close !== null
        ? latestBar.close - latestBar.open
        : null;
    const chgPct =
      chg !== null && latestBar.open && latestBar.open > 0 ? chg / latestBar.open : null;

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

  // Formatter helpers
  const formatVnd = (val: number | null | undefined): string => {
    if (val === null || val === undefined || isNaN(val)) return "—";
    return val.toLocaleString("en-US", { maximumFractionDigits: 1 });
  };

  const formatVol = (val: number | null | undefined): string => {
    if (val === null || val === undefined || isNaN(val)) return "—";
    if (val >= 1_000_000) return `${(val / 1_000_000).toFixed(2)}M`;
    if (val >= 1_000) return `${(val / 1_000).toFixed(1)}k`;
    return val.toLocaleString("en-US");
  };

  // Convert YYYY-MM-DD or datetime to lightweight-charts UTCTimestamp (seconds)
  const toChartTime = useCallback((dateStr: string): Time => {
    if (!dateStr) return 0 as Time;
    if (typeof dateStr === "number") {
      return (dateStr > 1e11 ? Math.floor(dateStr / 1000) : dateStr) as Time;
    }
    // YYYY-MM-DD format
    if (/^\d{4}-\d{2}-\d{2}$/.test(dateStr)) {
      return Math.floor(Date.parse(`${dateStr}T00:00:00Z`) / 1000) as Time;
    }
    // YYYY-MM-DD HH:mm or YYYY-MM-DD HH:mm:ss
    const isoStr = dateStr.includes("T") ? dateStr : dateStr.replace(" ", "T");
    const parsed = Date.parse(isoStr.endsWith("Z") || isoStr.includes("+") ? isoStr : `${isoStr}Z`);
    if (!isNaN(parsed)) {
      return Math.floor(parsed / 1000) as Time;
    }
    const fallback = new Date(dateStr).getTime();
    return (isNaN(fallback) ? 0 : Math.floor(fallback / 1000)) as Time;
  }, []);

  const prepareSeriesData = useCallback(<T extends { time: Time }>(items: T[]): T[] => {
    const map = new Map<number, T>();
    for (const item of items) {
      const t = Number(item.time) || 0;
      if (t > 0) {
        map.set(t, item);
      }
    }
    const arr = Array.from(map.values());
    arr.sort((a, b) => (Number(a.time) || 0) - (Number(b.time) || 0));
    return arr;
  }, []);

  // Initialize and build chart
  useEffect(() => {
    if (!chartContainerRef.current) return;

    // Clean up prior instance
    if (chartInstanceRef.current) {
      chartInstanceRef.current.remove();
      chartInstanceRef.current = null;
    }

    const chart = createChart(chartContainerRef.current, {
      width: chartContainerRef.current.clientWidth || 500,
      height,
      layout: {
        background: { type: ColorType.Solid, color: "#111418" },
        textColor: "#94a3b8",
        fontSize: 11,
        fontFamily: "'JetBrains Mono', monospace",
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
          style: 3, // dashed
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
        scaleMargins: {
          top: 0.1,
          bottom: mode === "RELATIVE" ? 0.1 : 0.25, // Leave bottom 25% for volume
        },
      },
      timeScale: {
        borderColor: "rgba(255, 255, 255, 0.08)",
        timeVisible: interval === "1m" || interval === "5m" || interval === "15m" || interval === "30m" || interval === "1h",
        secondsVisible: false,
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

    // Build series based on mode
    if (mode === "RELATIVE") {
      // Relative Normalized Performance Mode (Base 100)
      const relData = calculateNormalizedRelative(effectiveCwBars, effectiveUndBars);

      const cwLineSeries = chart.addSeries(LineSeries, {
        color: "#60a5fa", // Bright blue for CW
        lineWidth: 2,
        title: symbol,
        priceFormat: {
          type: "custom",
          formatter: (price: number) => `${price.toFixed(1)}%`,
        },
      });

      const undLineSeries = chart.addSeries(LineSeries, {
        color: "#f59e0b", // Warm amber for Underlying
        lineWidth: 2,
        title: underlyingSymbol || "Underlying",
        priceFormat: {
          type: "custom",
          formatter: (price: number) => `${price.toFixed(1)}%`,
        },
      });

      const cwPoints: LineData[] = [];
      const undPoints: LineData[] = [];

      for (const pt of relData) {
        const time = toChartTime(pt.time);
        if (pt.cw !== null) cwPoints.push({ time, value: pt.cw });
        if (pt.underlying !== null) undPoints.push({ time, value: pt.underlying });
      }

      cwLineSeries.setData(prepareSeriesData(cwPoints));
      undLineSeries.setData(prepareSeriesData(undPoints));

      relativeCwSeriesRef.current = cwLineSeries;
      relativeUndSeriesRef.current = undLineSeries;
    } else if (mode === "BOTH" && isCW) {
      // Both Mode: Stacked synchronized series
      const cwSeries = chart.addSeries(CandlestickSeries, {
        upColor: "#22c55e",
        downColor: "#ef4444",
        borderVisible: false,
        wickUpColor: "#22c55e",
        wickDownColor: "#ef4444",
        priceScaleId: "right",
      });

      const undSeries = chart.addSeries(LineSeries, {
        color: "#f59e0b",
        lineWidth: 2,
        priceScaleId: "undScale",
        title: underlyingSymbol || "Underlying",
      });

      chart.priceScale("undScale").applyOptions({
        scaleMargins: {
          top: 0.7,
          bottom: 0.05,
        },
      });

      const candleData: CandlestickData[] = effectiveCwBars
        .filter((b) => b.open !== null && b.high !== null && b.low !== null && b.close !== null)
        .map((b) => ({
          time: toChartTime(b.date),
          open: b.open!,
          high: b.high!,
          low: b.low!,
          close: b.close!,
        }));

      const undData: LineData[] = effectiveUndBars
        .filter((b) => b.close !== null && !isNaN(b.close!))
        .map((b) => ({
          time: toChartTime(b.date),
          value: b.close!,
        }));

      cwSeries.setData(prepareSeriesData(candleData));
      undSeries.setData(prepareSeriesData(undData));

      candleSeriesRef.current = cwSeries;
      undCandleSeriesRef.current = cwSeries;
    } else {
      // Single Instrument Mode (Stock or CW or Underlying Only)
      const targetBars = mode === "UNDERLYING" ? effectiveUndBars : effectiveCwBars;

      const mainCandleSeries = chart.addSeries(CandlestickSeries, {
        upColor: "#22c55e",
        downColor: "#ef4444",
        borderVisible: false,
        wickUpColor: "#22c55e",
        wickDownColor: "#ef4444",
      });

      const volumeSeries = chart.addSeries(HistogramSeries, {
        priceFormat: { type: "volume" },
        priceScaleId: "volScale",
      });

      chart.priceScale("volScale").applyOptions({
        scaleMargins: {
          top: 0.8,
          bottom: 0,
        },
      });

      const candleData: CandlestickData[] = [];
      const volumeData: HistogramData[] = [];

      for (const b of targetBars) {
        if (b.open !== null && b.high !== null && b.low !== null && b.close !== null) {
          const time = toChartTime(b.date);
          candleData.push({
            time,
            open: b.open,
            high: b.high,
            low: b.low,
            close: b.close,
          });

          if (b.volume !== null && b.volume >= 0) {
            const isUp = b.close >= b.open;
            volumeData.push({
              time,
              value: b.volume,
              color: isUp ? "rgba(34, 197, 94, 0.4)" : "rgba(239, 68, 68, 0.4)",
            });
          }
        }
      }

      mainCandleSeries.setData(prepareSeriesData(candleData));
      volumeSeries.setData(prepareSeriesData(volumeData));

      candleSeriesRef.current = mainCandleSeries;
      volumeSeriesRef.current = volumeSeries;

      // Reference Price Line for Stocks
      if (referencePrice && referencePrice > 0 && overlays.has("REF")) {
        mainCandleSeries.createPriceLine({
          price: referencePrice,
          color: "#eab308",
          lineWidth: 1,
          lineStyle: 2, // Dashed
          axisLabelVisible: true,
          title: "REF",
        });
      }

      // Technical Overlays
      if (overlays.has("EMA20")) {
        const ema20 = calculateEMA(targetBars, 20);
        const emaSeries = chart.addSeries(LineSeries, { color: "#38bdf8", lineWidth: 1, title: "EMA 20" });
        emaSeries.setData(prepareSeriesData(ema20.map((p) => ({ time: toChartTime(p.time), value: p.value }))));
        overlaySeriesMapRef.current.set("EMA20", emaSeries);
      }

      if (overlays.has("EMA50")) {
        const ema50 = calculateEMA(targetBars, 50);
        const emaSeries = chart.addSeries(LineSeries, { color: "#fb923c", lineWidth: 1, title: "EMA 50" });
        emaSeries.setData(prepareSeriesData(ema50.map((p) => ({ time: toChartTime(p.time), value: p.value }))));
        overlaySeriesMapRef.current.set("EMA50", emaSeries);
      }

      if (overlays.has("EMA200")) {
        const ema200 = calculateEMA(targetBars, 200);
        const emaSeries = chart.addSeries(LineSeries, { color: "#c084fc", lineWidth: 1, title: "EMA 200" });
        emaSeries.setData(prepareSeriesData(ema200.map((p) => ({ time: toChartTime(p.time), value: p.value }))));
        overlaySeriesMapRef.current.set("EMA200", emaSeries);
      }

      if (overlays.has("VWAP")) {
        const vwap = calculateVWAP(targetBars);
        if (vwap.length > 0) {
          const vwapSeries = chart.addSeries(LineSeries, { color: "#2dd4bf", lineWidth: 1, title: "VWAP" });
          vwapSeries.setData(prepareSeriesData(vwap.map((p) => ({ time: toChartTime(p.time), value: p.value }))));
          overlaySeriesMapRef.current.set("VWAP", vwapSeries);
        }
      }
    }

    // Auto-fit content on initial load
    chart.timeScale().fitContent();

    // Crosshair move listener for interactive OHLCV header readout
    chart.subscribeCrosshairMove((param) => {
      if (!param || !param.time || !param.seriesData) {
        setHoveredReadout(null);
        return;
      }

      const activeSeries = candleSeriesRef.current;
      if (activeSeries && param.seriesData.has(activeSeries)) {
        const data = param.seriesData.get(activeSeries) as any;
        if (data && data.open !== undefined) {
          const chg = data.close - data.open;
          const chgPct = data.open > 0 ? chg / data.open : 0;
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
            changePercent: chgPct,
          });
        }
      }
    });

    // Resize observer
    const resizeObserver = new ResizeObserver((entries) => {
      if (entries.length > 0 && chartInstanceRef.current && chartContainerRef.current) {
        const { width } = entries[0].contentRect;
        chartInstanceRef.current.applyOptions({ width, height });
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
  }, [
    symbol,
    underlyingSymbol,
    isCW,
    mode,
    effectiveCwBars,
    effectiveUndBars,
    overlays,
    referencePrice,
    height,
    interval,
    toChartTime,
  ]);

  const handleResetZoom = () => {
    if (chartInstanceRef.current) {
      chartInstanceRef.current.timeScale().fitContent();
    }
  };

  const hasData =
    mode === "UNDERLYING"
      ? effectiveUndBars.length > 0
      : effectiveCwBars.length > 0 || (mode === "RELATIVE" && (effectiveCwBars.length > 0 || effectiveUndBars.length > 0));

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "8px", width: "100%" }}>
      {/* Interactive OHLCV Readout Header */}
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
        <div style={{ display: "flex", alignItems: "center", gap: "12px", flexWrap: "wrap" }}>
          {/* Symbol and Interval Badge */}
          <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
            <span style={{ fontWeight: 600, color: "var(--foreground)" }} className="tnum">
              {activeReadout ? activeReadout.symbol : symbol}
            </span>
            <span style={{ color: "var(--subtle-foreground)" }}>·</span>
            <span style={{ color: "var(--primary)", fontWeight: 500 }}>{interval}</span>
          </div>

          {/* Current Close & Change */}
          {activeReadout && activeReadout.close !== null && (
            <div style={{ display: "flex", alignItems: "center", gap: "6px" }} className="tnum">
              <span style={{ fontWeight: 600, fontSize: "12px", color: "var(--foreground)" }}>
                {formatVnd(activeReadout.close)} ₫
              </span>
              {activeReadout.change !== null && activeReadout.changePercent !== null && (
                <span
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

          {/* OHLCV Detailed Pill Readout */}
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
                O <strong style={{ color: "var(--foreground)" }}>{formatVnd(activeReadout.open)}</strong>
              </span>
              <span>
                H <strong style={{ color: "var(--foreground)" }}>{formatVnd(activeReadout.high)}</strong>
              </span>
              <span>
                L <strong style={{ color: "var(--foreground)" }}>{formatVnd(activeReadout.low)}</strong>
              </span>
              <span>
                C <strong style={{ color: "var(--foreground)" }}>{formatVnd(activeReadout.close)}</strong>
              </span>
              {activeReadout.volume !== null && activeReadout.volume > 0 && (
                <span>
                  V <strong style={{ color: "var(--foreground)" }}>{formatVol(activeReadout.volume)}</strong>
                </span>
              )}
            </div>
          )}
        </div>

        {/* Fit / Reset Viewport Button */}
        <button
          onClick={handleResetZoom}
          className="focus-ring"
          title="Fit Visible Dataset (Double-Click)"
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

      {/* Main Interactive Canvas Container */}
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
            <span>No historical trade candles available for this interval.</span>
            {isCW && (
              <span style={{ fontSize: "11px", color: "var(--muted-foreground)" }}>
                Covered Warrants without matching trades do not generate fake candles.
              </span>
            )}
          </div>
        )}
      </div>

      {/* Relative Mode Legend Notice */}
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
              <span style={{ width: "8px", height: "2px", backgroundColor: "#60a5fa" }} />
              <strong style={{ color: "#60a5fa" }}>{symbol}</strong>
            </span>
            <span style={{ display: "flex", alignItems: "center", gap: "4px" }}>
              <span style={{ width: "8px", height: "2px", backgroundColor: "#f59e0b" }} />
              <strong style={{ color: "#f59e0b" }}>{underlyingSymbol || "Underlying"}</strong>
            </span>
          </div>
          <span>NORMALIZED PERFORMANCE (Base = 100)</span>
        </div>
      )}
    </div>
  );
}
