// @vitest-environment happy-dom
import { act, cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TradingChart } from "@/components/common/trading_chart";

const chart = vi.hoisted(() => ({
  series: [] as {
    kind: string;
    setData: ReturnType<typeof vi.fn>;
    createPriceLine: ReturnType<typeof vi.fn>;
  }[],
  hover: (_event: any) => {},
}));
vi.mock("lightweight-charts", () => ({
  ColorType: { Solid: "solid" },
  CrosshairMode: { Normal: 0 },
  CandlestickSeries: "candle",
  HistogramSeries: "volume",
  LineSeries: "line",
  createChart: () => ({
    addSeries: (kind: string) => {
      const series = {
        kind,
        setData: vi.fn(),
        update: vi.fn(),
        createPriceLine: vi.fn(),
      };
      chart.series.push(series);
      return series;
    },
    timeScale: () => ({ fitContent: vi.fn(), setVisibleLogicalRange: vi.fn() }),
    priceScale: () => ({ applyOptions: vi.fn() }),
    subscribeCrosshairMove: (listener: typeof chart.hover) => {
      chart.hover = listener;
    },
    applyOptions: vi.fn(),
    remove: vi.fn(),
  }),
}));
beforeEach(() => {
  chart.series = [];
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      disconnect() {}
    },
  );
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Chart OHLCV readout", () => {
  it("shows one close followed by change, and retains hovered volume including zero", () => {
    const page = render(
      <TradingChart
        symbol="HPG"
        bars={[
          {
            symbol: "HPG",
            date: "2026-08-27",
            open: 100,
            high: 130,
            low: 90,
            close: 115,
            volume: 5000,
          },
        ]}
      />,
    );
    expect(page.getAllByText("115")).toHaveLength(1);
    const change = page.getByTitle("Bar change: close − open");
    expect(change.previousElementSibling?.textContent).toBe("C 115");
    expect(change.textContent).toBe("+15 (+15.00%)");
    expect(page.getByText("5.0k")).toBeTruthy();
    expect(page.queryByText(/LAST 2026/)).toBeNull();
    const candle = chart.series.find((s) => s.kind === "candle")!;
    const volume = chart.series.find((s) => s.kind === "volume")!;
    const hover = (amount: number) =>
      act(() =>
        chart.hover({
          time: 12345,
          seriesData: new Map([
            [candle, { open: 95, high: 105, low: 90, close: 100 }],
            [volume, { value: amount }],
          ]),
        }),
      );
    hover(3000);
    expect(page.getByText("3.0k")).toBeTruthy();
    expect(page.queryByText("5.0k")).toBeNull();
    hover(0);
    expect(page.getByText("0").parentElement?.textContent).toBe("V 0");
    act(() => chart.hover({}));
    expect(page.getByText("5.0k")).toBeTruthy();
  });
});
