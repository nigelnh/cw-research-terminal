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
    timeScale: () => ({ getVisibleLogicalRange: () => null, fitContent: vi.fn(), setVisibleLogicalRange: vi.fn() }),
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
    expect(change.textContent).toBe("15 (15.00%)");
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

  // The chart header carried a provenance strip - "2026-08-27 · RAW · MARKET_TRADE_FEED",
  // plus " · PARTIAL" on a forming bar and "Basis unavailable" / "Source unavailable" when
  // a bar lacked either. It read as debug output left in by accident, so it is gone. The
  // provenance itself is untouched: the API still carries it and `aggregateProvenance`
  // still tests it. This pins the strip out of the header, the same way the overview card
  // pins its removed POLLED / PARTIAL row.
  it("does not print provenance in the header", () => {
    const page = render(
      <TradingChart
        symbol="HPG"
        bars={[
          {
            symbol: "HPG",
            date: "2026-08-27",
            open: 100, high: 130, low: 90, close: 115, volume: 5000,
            sessionDate: "2026-08-27",
            priceBasis: "RAW",
            source: "MARKET_TRADE_FEED",
            complete: false,
          } as never,
        ]}
      />,
    );
    for (const leaked of [/RAW/, /MARKET_TRADE_FEED/, /PARTIAL/, /Basis unavailable/, /Source unavailable/]) {
      expect(page.queryByText(leaked)).toBeNull();
    }
    // ...while the readout it shares a row with still works.
    expect(page.getAllByText("115")).toHaveLength(1);
    expect(page.getByText("5.0k")).toBeTruthy();
  });
});

describe("Chart follows the live quote on 1D", () => {
  // The screenshot: the tape printed 20,200 at 09:36:16 while the candle and the readout
  // still closed at 20,250 - the history snapshot refetches once a minute.
  const staleToday = [
    { symbol: "HPG", date: "2026-09-29", sessionDate: "2026-09-29", open: 20200, high: 20400, low: 20150, close: 20250, volume: 2_740_000 },
  ];
  const now = Date.now();
  const live = {
    symbol: "HPG",
    lastPrice: 20200, openPrice: 20200, highPrice: 20400, lowPrice: 20150, totalVolume: 2_900_000,
    marketSessionDate: "2026-09-29",
    tradeTimestamp: Date.parse("2026-09-29T02:36:16Z"),
    exchangeTimestamp: null, sourceTimestamp: null, receivedTimestamp: now,
    // Fresh pulses on every field the readout shows: before this change each one washed
    // the digits green or grey for 1.2 s on every tick.
    realtimePulses: Object.fromEntries(
      ["openPrice", "highPrice", "lowPrice", "lastPrice", "priceChange", "priceChangePercent", "totalVolume"]
        .map((field, i) => [field, { sequence: i + 1, direction: "down", startedAt: now }]),
    ),
  } as never;

  it("closes the candle and the readout at the live print", () => {
    const page = render(<TradingChart symbol="HPG" interval="1D" bars={staleToday} liveQuote={live} />);
    const change = page.getByTitle("Bar change: close − open");
    expect(change.previousElementSibling?.textContent).toBe("C 20,200");
    expect(page.getByText("2.90M")).toBeTruthy();

    const candle = chart.series.find((s) => s.kind === "candle")!;
    const calls = candle.setData.mock.calls;
    const drawn = calls[calls.length - 1][0] as { close: number }[];
    expect(drawn[drawn.length - 1].close).toBe(20200);
  });

  it("updates the readout without flashing it", () => {
    const page = render(<TradingChart symbol="HPG" interval="1D" bars={staleToday} liveQuote={live} />);
    expect(page.container.querySelector(".realtime-flash")).toBeNull();
    expect(page.container.querySelector("[data-flash-direction]")).toBeNull();
  });

  it("leaves intraday candles to the backend", () => {
    const page = render(<TradingChart symbol="HPG" interval="5m" bars={staleToday} liveQuote={live} />);
    const change = page.getByTitle("Bar change: close − open");
    expect(change.previousElementSibling?.textContent).toBe("C 20,250");
  });
});
