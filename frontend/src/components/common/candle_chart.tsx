/**
 * Financial Candlestick Chart Component (TradingView Lightweight Charts)
 */

import { TradingChart } from "./trading_chart";
import type { HistoricalBar, UnderlyingClosePoint } from "@/domain/models";
import type { ChartInterval, ChartRange } from "@/domain/historical/types";

export type Timeframe = "1D" | "5D" | "1M" | "3M" | "6M" | "1Y";

export type Props = {
  bars: HistoricalBar[];
  compare?: UnderlyingClosePoint[] | null;
  compareLabel?: string;
  timeframe?: Timeframe;
  height?: number;
  symbol?: string;
};

export function CandleChart({
  bars,
  compare,
  compareLabel,
  timeframe = "3M",
  height = 240,
  symbol = "CHART",
}: Props) {
  const rangeMap: Record<string, ChartRange> = {
    "1D": "1D",
    "5D": "5D",
    "1M": "1M",
    "3M": "3M",
    "6M": "6M",
    "1Y": "1Y",
  };
  const intervalMap: Record<string, ChartInterval> = {
    "1D": "5m",
    "5D": "30m",
    "1M": "1D",
    "3M": "1D",
    "6M": "1D",
    "1Y": "1D",
  };

  return (
    <TradingChart
      symbol={symbol}
      bars={bars}
      underlyingBars={compare}
      underlyingSymbol={compareLabel}
      range={rangeMap[timeframe] || "3M"}
      interval={intervalMap[timeframe] || "1D"}
      mode={compare && compare.length > 0 ? "BOTH" : "CW"}
      height={height}
    />
  );
}

export { TradingChart };
