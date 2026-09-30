// @vitest-environment happy-dom
import { act, cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TradingChart } from "@/components/common/trading_chart";

const chart = vi.hoisted(() => ({
  created: [] as { width: number; height: number }[],
  applied: [] as { width?: number; height?: number }[],
  resize: null as null | ((entries: { contentRect: { width: number; height: number } }[]) => void),
}));
vi.mock("lightweight-charts", () => ({
  ColorType: { Solid: "solid" },
  CrosshairMode: { Normal: 0 },
  CandlestickSeries: "candle",
  HistogramSeries: "volume",
  LineSeries: "line",
  createChart: (_el: HTMLElement, options: { width: number; height: number }) => {
    chart.created.push({ width: options.width, height: options.height });
    return {
      addSeries: () => ({ setData: vi.fn(), update: vi.fn(), createPriceLine: vi.fn() }),
      timeScale: () => ({ getVisibleLogicalRange: () => null, fitContent: vi.fn(), setVisibleLogicalRange: vi.fn() }),
      priceScale: () => ({ applyOptions: vi.fn() }),
      subscribeCrosshairMove: vi.fn(),
      applyOptions: (options: { width?: number; height?: number }) => chart.applied.push(options),
      remove: vi.fn(),
    };
  },
}));

beforeEach(() => {
  chart.created = [];
  chart.applied = [];
  chart.resize = null;
  vi.stubGlobal(
    "ResizeObserver",
    class {
      constructor(callback: typeof chart.resize) {
        chart.resize = callback;
      }
      observe() {}
      disconnect() {}
    },
  );
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const bars = [{ symbol: "HPG", date: "2026-09-30", open: 20300, high: 20500, low: 20150, close: 20150, volume: 13_350_300 }];

function canvasBox(container: HTMLElement): HTMLElement {
  const box = Array.from(container.querySelectorAll<HTMLElement>("div")).find(
    (d) => d.style.backgroundColor === "rgb(17, 20, 24)" || d.style.backgroundColor === "#111418",
  );
  if (!box) throw new Error("chart canvas container not found");
  return box;
}

describe("Chart height", () => {
  it("a filling chart takes its height from its container, not a constant", () => {
    const page = render(<TradingChart symbol="HPG" bars={bars} fill />);
    const box = canvasBox(page.container);
    expect(box.style.height).toBe("");
    expect(box.style.flex).toContain("1");

    act(() => chart.resize?.([{ contentRect: { width: 812, height: 243.6 } }]));
    expect(chart.applied[chart.applied.length - 1]).toEqual({ width: 812, height: 243 });
  });

  it("a fixed chart keeps its height whatever its container does", () => {
    const page = render(<TradingChart symbol="HPG" bars={bars} height={300} />);
    expect(canvasBox(page.container).style.height).toBe("300px");
    expect(chart.created[chart.created.length - 1]?.height).toBe(300);

    act(() => chart.resize?.([{ contentRect: { width: 812, height: 243 } }]));
    expect(chart.applied[chart.applied.length - 1]).toEqual({ width: 812, height: 300 });
  });
});
