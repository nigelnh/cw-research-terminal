// @vitest-environment happy-dom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MarketOverviewStrip, Sparkline } from "@/features/watchlist/market_overview_strip";

const state = vi.hoisted(() => ({ empty: false, refreshing: false }));
vi.mock("@/data/query/use_market_overview", () => ({
  useMarketOverview: () => ({
    isLoading: false,
    data: state.empty ? {
      indices: [], top_stock_volume: [], top_cw_volume: [],
      availability: "UNAVAILABLE", refreshing: state.refreshing,
    } : {
      indices: ["VN30", "VNINDEX", "VNFINLEAD", "VNDIAMOND"].map((symbol) => ({
        symbol, value: 1831.56, change: 3.2, change_percent: 0.18,
        volume: 1000000, trading_value: 2000000000, advancing: 12,
        ceiling: 1, unchanged: 5, declining: 9, floor: 2,
        as_of: "2026-09-02T14:00:00+07:00", sparkline: [1, 2, 1.5, 3],
      })),
      top_stock_volume: [{ symbol: "HPG", volume: 17126700, price: 22100, market_state: "DOWN", as_of: "2026-09-02" }],
      top_cw_volume: [{ symbol: "CHPG2617", volume: 306800, price: 490, market_state: "REFERENCE", as_of: "2026-09-02" }],
      as_of: "2026-09-02T14:00:00+07:00", market_session_active: true,
      stock_scope: "HOSE (VNINDEX constituents)", cw_scope: "verified active CW registry", source: "FIINQUANT",
    },
  }),
}));
afterEach(() => {
  cleanup();
  state.empty = false;
  state.refreshing = false;
});

describe("market overview strip", () => {
  it("renders a single real observation and keeps missing intraday buckets as gaps", () => {
    const { container, rerender } = render(<Sparkline direction={1} reference={100}
      values={[{ timestamp: "2026-09-04T09:15:00+07:00", value: 101 }]} />);
    expect(container.querySelector("circle")).not.toBeNull();
    expect(screen.queryByText("NO INTRADAY SERIES")).toBeNull();
    rerender(<Sparkline direction={1} reference={100} values={[
      { timestamp: "2026-09-04T09:15:00+07:00", value: 101 },
      { timestamp: "2026-09-04T09:20:00+07:00", value: 102 },
      { timestamp: "2026-09-04T09:35:00+07:00", value: 103 },
      { timestamp: "2026-09-04T09:40:00+07:00", value: 104 },
    ]} />);
    expect(container.querySelectorAll("polyline")).toHaveLength(2);
    expect(container.querySelector("line")?.getAttribute("y1")).toBe("30");
  });

  it("maps the intraday path onto a fixed 09:00-15:00 ICT x-axis", () => {
    const { container } = render(<Sparkline direction={1} reference={100} values={[
      { timestamp: "2026-09-04T09:00:00+07:00", value: 100 },
      { timestamp: "2026-09-04T12:00:00+07:00", value: 105 },
    ]} />);
    // the >7.5min gaps make each bar its own segment -> two circles at fixed x
    const cx = [...container.querySelectorAll("circle")].map(c => Number(c.getAttribute("cx")));
    expect(cx[0]).toBeCloseTo(0, 1);      // 09:00 -> left edge
    expect(cx[1]).toBeCloseTo(50, 1);     // 12:00 -> half-way through the 6h session
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

  it("can render the compact index-only variant", () => {
    render(<MarketOverviewStrip indicesOnly />);
    expect(screen.getAllByRole("article")).toHaveLength(4);
    expect(screen.queryByText("Top Stock Trading Volume")).toBeNull();
    expect(screen.queryByText("Top Covered Warrants Trading Volume")).toBeNull();
  });
});
