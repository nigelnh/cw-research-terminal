// @vitest-environment happy-dom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { IntradayVolume, MarketOverviewStrip, Sparkline } from "@/features/watchlist/market_overview_strip";

const state = vi.hoisted(() => ({ empty: false, refreshing: false, preOpen: false, stale: false }));
vi.mock("@/data/query/use_market_overview", () => ({
  useMarketOverview: () => ({
    isLoading: false,
    data: state.empty ? {
      indices: [], top_stock_volume: [], top_cw_volume: [],
      availability: "UNAVAILABLE", refreshing: state.refreshing,
    } : {
      indices: ["VN30", "VNINDEX", "VNFINLEAD", "VNDIAMOND"].map((symbol) => ({
        symbol, value: 1831.56, reference: 1828.36, change: 3.2, change_percent: 0.18,
        volume: 1000000, trading_value: 2000000000, advancing: 12,
        ceiling: 1, unchanged: 5, declining: 9, floor: 2,
        as_of: "2026-09-02T14:00:00+07:00", sparkline: [1, 2, 1.5, 3], stale: state.stale,
      })),
      top_stock_volume: [{ symbol: "HPG", volume: 17126700, price: 22100, market_state: "DOWN", as_of: "2026-09-02" }],
      top_cw_volume: [{ symbol: "CHPG2617", volume: 306800, price: 490, market_state: "REFERENCE", as_of: "2026-09-02" }],
      as_of: "2026-09-02T14:00:00+07:00", market_session_active: true,
      market_phase: state.preOpen ? "PRE_OPEN" : "CONTINUOUS_PM",
      stock_scope: "HOSE (VNINDEX constituents)", cw_scope: "verified active CW registry", source: "FIINQUANT",
    },
  }),
}));
afterEach(() => {
  cleanup();
  state.empty = false;
  state.refreshing = false;
  state.preOpen = false;
  state.stale = false;
});

describe("market overview strip", () => {
  it("renders a single real observation and keeps missing intraday buckets as gaps", () => {
    const { container, rerender } = render(<Sparkline reference={100}
      values={[{ timestamp: "2026-09-04T09:15:00+07:00", value: 101 }]} />);
    expect(container.querySelector("circle")).not.toBeNull();
    expect(screen.queryByText("NO INTRADAY SERIES")).toBeNull();
    rerender(<Sparkline reference={100} values={[
      { timestamp: "2026-09-04T09:15:00+07:00", value: 101 },
      { timestamp: "2026-09-04T09:20:00+07:00", value: 102 },
      { timestamp: "2026-09-04T09:35:00+07:00", value: 103 },
      { timestamp: "2026-09-04T09:40:00+07:00", value: 104 },
    ]} />);
    expect(container.querySelectorAll("polyline")).toHaveLength(2);
    // the reference line always sits dead center (y 5..30 plot area -> mid 17.5),
    // regardless of where the data falls, so it reads at a glance
    expect(container.querySelector("line")?.getAttribute("y1")).toBe("17.5");
  });

  it("keeps the reference line centered even when the whole session trades on one side of it", () => {
    const { container } = render(<Sparkline reference={100} values={[
      { timestamp: "2026-09-04T09:15:00+07:00", value: 140 },
      { timestamp: "2026-09-04T09:20:00+07:00", value: 180 },
    ]} />);
    expect(container.querySelector("line")?.getAttribute("y1")).toBe("17.5");
  });

  it("colors the path green above the reference and red at/below it, splitting exactly at the crossing", () => {
    const { container } = render(<Sparkline reference={100} values={[
      { timestamp: "2026-09-04T09:15:00+07:00", value: 110 }, // above
      { timestamp: "2026-09-04T09:20:00+07:00", value: 90 },  // below
    ]} />);
    const lines = [...container.querySelectorAll("polyline")];
    expect(lines).toHaveLength(2);
    expect(lines[0].getAttribute("stroke")).toBe("var(--up)");
    expect(lines[1].getAttribute("stroke")).toBe("var(--down)");
    // both segments share the interpolated crossing point (continuous line, clean join)
    const end0points = lines[0].getAttribute("points")?.trim().split(" ") ?? [];
    const end0 = end0points[end0points.length - 1];
    const start1 = lines[1].getAttribute("points")?.trim().split(" ")[0];
    expect(end0).toBe(start1);
  });

  it("a value exactly at the reference counts as the up (green) side", () => {
    const { container } = render(<Sparkline reference={100} values={[
      { timestamp: "2026-09-04T09:15:00+07:00", value: 100 },
      { timestamp: "2026-09-04T09:20:00+07:00", value: 105 },
    ]} />);
    expect(container.querySelector("polyline")?.getAttribute("stroke")).toBe("var(--up)");
  });

  it("maps the intraday path onto a fixed 09:00-15:00 ICT x-axis", () => {
    const { container } = render(<Sparkline reference={100} values={[
      { timestamp: "2026-09-04T09:00:00+07:00", value: 100 },
      { timestamp: "2026-09-04T12:00:00+07:00", value: 105 },
    ]} />);
    // the >7.5min gaps make each bar its own segment -> two circles at fixed x
    const cx = [...container.querySelectorAll("circle")].map(c => Number(c.getAttribute("cx")));
    expect(cx[0]).toBeCloseTo(0, 1);      // 09:00 -> left edge
    expect(cx[1]).toBeCloseTo(50, 1);     // 12:00 -> half-way through the 6h session
  });

  it("bridges the 11:30-13:00 lunch break instead of leaving a gap", () => {
    const { container } = render(<Sparkline reference={100} values={[
      { timestamp: "2026-09-04T11:25:00+07:00", value: 101 },
      { timestamp: "2026-09-04T11:30:00+07:00", value: 102 },
      { timestamp: "2026-09-04T13:00:00+07:00", value: 103 },
      { timestamp: "2026-09-04T13:05:00+07:00", value: 104 },
    ]} />);
    // one continuous polyline across lunch; a non-lunch 90min gap would split it in two
    expect(container.querySelectorAll("polyline")).toHaveLength(1);
    expect(container.querySelector("polyline")?.getAttribute("points")?.split(" ")).toHaveLength(4);
  });
  it("shows bounded background updating state without fabricated index values", () => {
    state.empty = true;
    state.refreshing = true;
    render(<MarketOverviewStrip />);
    expect(screen.getByText("MARKET OVERVIEW UPDATING…")).toBeTruthy();
    expect(screen.queryAllByRole("article")).toHaveLength(0);
    expect(screen.queryByText("LOADING MARKET OVERVIEW…")).toBeNull();
  });

  it("shows unavailable when refresh has failed", () => {
    state.empty = true;
    render(<MarketOverviewStrip />);
    expect(screen.getByText("MARKET OVERVIEW UNAVAILABLE")).toBeTruthy();
  });

  it("shows only today's references and blank leader slots during pre-open", () => {
    state.preOpen = true;
    render(<MarketOverviewStrip />);
    expect(screen.getAllByText("REF")).toHaveLength(4);
    expect(screen.getAllByText("1,828.36").length).toBeGreaterThanOrEqual(4);
    expect(screen.getAllByLabelText("Session reference price")).toHaveLength(4);
    expect(screen.getAllByLabelText("No ranked volume yet")).toHaveLength(10);
    expect(screen.queryByText("HPG")).toBeNull();
    expect(screen.queryByText("CHPG2617")).toBeNull();
    expect(document.querySelectorAll(".overview-direction-icon")).toHaveLength(0);
  });

  it("keeps requested index order and separates the two ranking scopes", () => {
    render(<MarketOverviewStrip />);
    const cards = screen.getAllByRole("article");
    expect(cards.map(card => card.getAttribute("aria-label"))).toEqual([
      "VN30 index overview", "VNINDEX index overview", "VNFINLEAD index overview", "VNDIAMOND index overview",
    ]);
    expect(screen.getByText("Top Stock Trading Volume")).toBeTruthy();
    expect(screen.getByText("Top Covered Warrants Trading Volume")).toBeTruthy();
    expect(screen.queryByText("HOSE covered warrants")).toBeNull();
    expect(screen.queryByText(/LAST SESSION/)).toBeNull();
    expect(screen.getByText("17,126,700")).toBeTruthy();
    expect(screen.getByText("HPG").style.color).toBe("var(--down)");
    expect(screen.getByText("22,100").style.color).toBe("var(--down)");
    expect(document.querySelectorAll(".overview-direction-icon")).toHaveLength(8);
    expect(screen.getAllByText("(1)")[0].style.color).toBe("var(--price-ceiling)");
    // the POLLED / PARTIAL status row was removed from the card
    expect(screen.queryByText(/POLLED|PARTIAL/)).toBeNull();
  });

  it("shows the observation time instead of a STALE label", () => {
    state.stale = true;
    render(<MarketOverviewStrip />);
    expect(screen.queryByText("STALE")).toBeNull();
    expect(screen.getAllByText("14:00")).toHaveLength(4);
  });

  it("can render the compact index-only variant", () => {
    render(<MarketOverviewStrip indicesOnly />);
    expect(screen.getAllByRole("article")).toHaveLength(4);
    expect(screen.queryByText("Top Stock Trading Volume")).toBeNull();
    expect(screen.queryByText("Top Covered Warrants Trading Volume")).toBeNull();
  });
});

describe("IntradayVolume — one bar per index-line point", () => {
  const pt = (hh: string, mm: string, value: number, volume: number) => ({
    timestamp: `2026-09-04T${hh}:${mm}:00+07:00`, value, volume,
  });

  it("draws exactly one <rect> per realized 5-minute bar, on the fixed session axis", () => {
    const values = [pt("09", "15", 101, 40), pt("09", "20", 102, 55), pt("09", "25", 103, 12), pt("13", "05", 104, 88)];
    const { container } = render(<IntradayVolume values={values} />);
    const rects = [...container.querySelectorAll("rect")];
    expect(rects).toHaveLength(values.length);
    const x = (r: Element) => Number(r.getAttribute("x"));
    const h = (r: Element) => Number(r.getAttribute("height"));
    // 09:15 sits near the left edge of the 09:00–15:00 axis; 13:05 is well past the middle
    expect(x(rects[0])).toBeGreaterThanOrEqual(0);
    expect(x(rects[0])).toBeLessThan(6);
    expect(x(rects[3])).toBeGreaterThan(60);
    // the svg spans the whole bottom band; bars scale to the busiest bar (vol 88 -> full)
    expect(container.querySelector("svg")?.getAttribute("viewBox")).toBe("0 0 100 100");
    expect(h(rects[3])).toBe(100);
    expect(h(rects[3])).toBeGreaterThan(h(rects[1]));
    expect(h(rects[1])).toBeGreaterThan(h(rects[2]));
  });

  it("renders nothing when the session has no intraday volume", () => {
    const { container } = render(<IntradayVolume values={[pt("09", "15", 101, 0), pt("09", "20", 102, 0)]} />);
    expect(container.querySelector("svg")).toBeNull();
    expect(container.firstChild).toBeNull();
  });

  it("ignores the legacy plain-number sparkline shape", () => {
    const { container } = render(<IntradayVolume values={[1, 2, 3] as never} />);
    expect(container.firstChild).toBeNull();
  });
});
