// @vitest-environment happy-dom
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, within } from "@testing-library/react";
import { ResearchUniverse } from "@/features/stock_research/research_universe";
import { AppHeader } from "@/components/common/app_header";
import { NewsFeed } from "@/features/news_feed/news_feed";

const fixture = vi.hoisted(() => {
  const instruments = [
    { symbol: "CVPB2615", underlyingSymbol: "VPB", issuer: "TCBS", strikePrice: 28000, exerciseRatio: 2, lastTradingDate: "2027-03-12", maturityDate: "2027-03-16" },
    { symbol: "CHPG2602", underlyingSymbol: "HPG", issuer: "ACBS", strikePrice: 25000, exerciseRatio: 4, lastTradingDate: "2026-12-14", maturityDate: "2026-12-18" },
    { symbol: "CHPG2603", underlyingSymbol: "HPG", issuer: "KISVN", strikePrice: 27000, exerciseRatio: 3, lastTradingDate: null, maturityDate: "2027-05-01" },
  ];
  const discovered = [...instruments,
    { symbol: "CMBB2601", underlyingSymbol: "MBB", issuer: "SSI", strikePrice: 24000, exerciseRatio: 2, lastTradingDate: "2027-06-01", maturityDate: "2027-06-03" },
  ];
  const feed = vi.fn(() => ({ items: [], isLoading: false, isError: false, isEmpty: true, hasNextPage: false, fetchNextPage: vi.fn(), refetch: vi.fn() }));
  return { instruments, discovered, feed, add: vi.fn() };
});
vi.mock("@/data/query", () => ({
  useActiveWarrants: (filter?: { status?: string }) => ({ instruments: filter?.status === "ALL" ? fixture.discovered : fixture.instruments, isLoading: false, isError: false }),
  useResearchFeed: fixture.feed,
}));
vi.mock("@/data/watchlist", () => ({ useWatchlist: () => ({ items: [], isInWatchlist: () => false, addToWatchlist: fixture.add }) }));
// The analytics band is exercised in research_analytics_band.test.tsx; these cases are
// about the registry tables, and stubbing it keeps chart.js out of this suite.
vi.mock("@/features/stock_research/research_analytics_band", () => ({ ResearchAnalyticsBand: () => null }));
vi.mock("@/data/query/use_stock_profiles", () => ({ useStockProfiles: () => ({ profiles: [
  { symbol: "HPG", name: "Hoa Phat Group", exchange: "HOSE" },
  { symbol: "VPB", name: "Vietnam Prosperity Bank", exchange: "HOSE" },
] }) }));
vi.mock("@/features/watchlist/market_overview_strip", () => ({ MarketOverviewStrip: () => null }));
vi.mock("@/data/auth", () => ({ useAuth: () => ({ isConfigured: false }) }));

afterEach(() => { cleanup(); window.localStorage.clear(); vi.clearAllMocks(); });

const rowOrder = (table: HTMLElement) => [...table.querySelectorAll("tbody tr[data-symbol]")].map(row => row.getAttribute("data-symbol"));
const headerOrder = (table: HTMLElement) => [...table.querySelectorAll("th[data-column]")].map(th => th.getAttribute("data-column"));
function drag(from: HTMLElement, to: HTMLElement) {
  const dataTransfer = { setData: vi.fn(), effectAllowed: "", dropEffect: "" };
  fireEvent.dragStart(from, { dataTransfer });
  fireEvent.dragOver(to, { dataTransfer });
  fireEvent.drop(to, { dataTransfer });
  fireEvent.dragEnd(from, { dataTransfer });
}

describe("Research table interactions", () => {
  it("submits search on Enter and highlights only the searched stock without selecting it or hiding CWs", () => {
    const select = vi.fn();
    const page = render(<ResearchUniverse onSelectSymbol={select} />);
    const input = page.getByRole("combobox", { name: "Search research symbols" });
    fireEvent.focus(input);
    expect(page.queryByRole("listbox")).toBeNull();
    fireEvent.change(input, { target: { value: "HPG" } });
    expect(page.container.querySelectorAll(".is-search-match")).toHaveLength(0);
    fireEvent.keyDown(input, { key: "Enter" });
    expect([...page.container.querySelectorAll(".is-search-match")].map(row => row.getAttribute("data-symbol"))).toEqual(["HPG"]);
    expect(rowOrder(page.getByRole("table", { name: "Covered warrants" }))).toHaveLength(3);
    expect(select).not.toHaveBeenCalled();
    fireEvent.change(input, { target: { value: "MBB" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(rowOrder(page.getByRole("table", { name: "Covered warrants" }))).toHaveLength(3);
    expect([...page.container.querySelectorAll(".is-search-match")]).toHaveLength(0);
    fireEvent.change(input, { target: { value: "CVPB" } });
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });
    expect((input as HTMLInputElement).value).toBe("CVPB2615");
    expect([...page.container.querySelectorAll(".is-search-match")].map(row => row.getAttribute("data-symbol"))).toEqual(["CVPB2615"]);
  });

  it("sorts dates in both directions, keeps missing dates last, and resets to source order", () => {
    const page = render(<ResearchUniverse />);
    const table = page.getByRole("table", { name: "Covered warrants" });
    const order = headerOrder(table);
    expect(order[order.indexOf("ratio") + 1]).toBe("lastTradingDate");
    const date = within(table).getByRole("columnheader", { name: "LAST_TRD_DATE" });
    fireEvent.click(date);
    expect(date.getAttribute("aria-sort")).toBe("ascending");
    expect(rowOrder(table)).toEqual(["CHPG2602", "CVPB2615", "CHPG2603"]);
    fireEvent.keyDown(date, { key: "Enter" });
    expect(rowOrder(table)).toEqual(["CVPB2615", "CHPG2602", "CHPG2603"]);
    fireEvent.keyDown(date, { key: " " });
    expect(date.getAttribute("aria-sort")).toBe("none");
    expect(rowOrder(table)).toEqual(fixture.instruments.map(row => row.symbol));
  });

  it("moves headers together with cells, supports keyboard moves and persists each table separately", () => {
    const page = render(<ResearchUniverse />);
    const cw = page.getByRole("table", { name: "Covered warrants" });
    const stocks = page.getByRole("table", { name: "Stocks" });
    drag(within(cw).getByRole("columnheader", { name: "LAST_TRD_DATE" }), within(cw).getByRole("columnheader", { name: "SYMBOL" }));
    expect(headerOrder(cw)[0]).toBe("lastTradingDate");
    expect(cw.querySelector('tr[data-symbol="CVPB2615"] td:nth-child(2)')?.textContent).toBe("2027-03-12");
    fireEvent.keyDown(within(stocks).getByRole("columnheader", { name: "EXCHANGE" }), { key: "ArrowLeft", altKey: true });
    expect(headerOrder(stocks)).toEqual(["exchange", "symbol"]);
    expect(headerOrder(cw)[0]).toBe("lastTradingDate");
    page.unmount();
    const restored = render(<ResearchUniverse />);
    expect(headerOrder(restored.getByRole("table", { name: "Covered warrants" }))[0]).toBe("lastTradingDate");
    expect(headerOrder(restored.getByRole("table", { name: "Stocks" }))).toEqual(["exchange", "symbol"]);
  });

  it("moves rows within their own table and keeps row actions separate from instrument selection", () => {
    const select = vi.fn();
    const page = render(<ResearchUniverse onSelectSymbol={select} />);
    const cw = page.getByRole("table", { name: "Covered warrants" });
    const stocks = page.getByRole("table", { name: "Stocks" });
    const row = (symbol: string) => page.container.querySelector(`tr[data-symbol="${symbol}"]`)! as HTMLElement;
    drag(row("CVPB2615"), row("CHPG2603"));
    expect(rowOrder(cw)).toEqual(["CHPG2602", "CHPG2603", "CVPB2615"]);
    drag(row("HPG"), row("VPB"));
    expect(rowOrder(stocks)).toEqual(["VPB", "HPG"]);
    drag(row("HPG"), row("CHPG2602"));
    expect(rowOrder(stocks)).toEqual(["VPB", "HPG"]);
    fireEvent.keyDown(row("CVPB2615"), { key: "ArrowUp", altKey: true });
    expect(rowOrder(cw)).toEqual(["CHPG2602", "CVPB2615", "CHPG2603"]);
    fireEvent.click(page.getByRole("button", { name: "Add HPG to watchlist" }));
    expect(fixture.add).toHaveBeenCalledWith({ symbol: "HPG", instrumentType: "STOCK" });
    expect(select).not.toHaveBeenCalled();
    fireEvent.keyDown(row("HPG"), { key: "Enter" });
    expect(select).toHaveBeenCalledWith("HPG");
    fireEvent.click(within(stocks).getByRole("columnheader", { name: "SYMBOL" }));
    expect(rowOrder(stocks)).toEqual(["HPG", "VPB"]);
  });
});

function NewsSearchHarness() {
  const [filter, setFilter] = useState("");
  return <><AppHeader activeTab="news" onTabChange={() => {}} filter={filter} onFilterChange={setFilter} marketSessionActive={false} />
    <NewsFeed filter={filter} selectedSymbol="HPG" /></>;
}

describe("Global search submission", () => {
  it("lists each symbol destination and jumps through the selected result", () => {
    const jump = vi.fn();
    const page = render(<AppHeader activeTab="dashboard" onTabChange={() => {}} filter="" onFilterChange={() => {}}
      marketSessionActive={false} onJump={jump} searchOptions={[
        { symbol: "HPG", destination: "dashboard", kind: "stock" },
        { symbol: "HPG", destination: "research", kind: "stock" },
        { symbol: "HPG", destination: "news", kind: "news" },
      ]} />);
    const input = page.getByRole("textbox", { name: "Filter or jump to symbol" });
    fireEvent.change(input, { target: { value: "HP" } });
    expect(page.getAllByRole("option").map(option => option.textContent)).toEqual([
      "HPGSTOCKWATCHLIST", "HPGSTOCKRESEARCH", "HPGNEWSNEWS",
    ]);
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(jump).toHaveBeenCalledWith({ symbol: "HPG", destination: "research", kind: "stock" });
  });

  it("waits for Enter and searches news text/symbols without interpreting dividend as a ticker", () => {
    const page = render(<NewsSearchHarness />);
    const input = page.getByRole("textbox", { name: "Filter or jump to symbol" });
    fireEvent.change(input, { target: { value: "dividend" } });
    expect(fixture.feed).toHaveBeenLastCalledWith(expect.objectContaining({ symbol: "HPG", query: undefined }));
    fireEvent.keyDown(input, { key: "Enter" });
    expect(fixture.feed).toHaveBeenLastCalledWith(expect.objectContaining({ symbol: undefined, query: "dividend" }));
    fireEvent.change(input, { target: { value: "VPB" } });
    expect(fixture.feed).toHaveBeenLastCalledWith(expect.objectContaining({ query: "dividend" }));
    fireEvent.keyDown(input, { key: "Escape" });
    expect((input as HTMLInputElement).value).toBe("dividend");
    fireEvent.change(input, { target: { value: "VPB" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(fixture.feed).toHaveBeenLastCalledWith(expect.objectContaining({ symbol: undefined, query: "VPB" }));
    fireEvent.change(input, { target: { value: "" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(fixture.feed).toHaveBeenLastCalledWith(expect.objectContaining({ symbol: "HPG", query: undefined }));
  });
});
