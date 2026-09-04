// @vitest-environment happy-dom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MarketOverviewStrip } from "@/features/watchlist/market_overview_strip";

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
  });

  it("can render the compact index-only variant", () => {
    render(<MarketOverviewStrip indicesOnly />);
    expect(screen.getAllByRole("article")).toHaveLength(4);
    expect(screen.queryByText("Top Stock Trading Volume")).toBeNull();
    expect(screen.queryByText("Top Covered Warrants Trading Volume")).toBeNull();
  });
});
