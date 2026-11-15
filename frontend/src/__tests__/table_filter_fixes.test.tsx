// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, within } from "@testing-library/react";
import { useState } from "react";
import { PersonalDashboard } from "@/features/watchlist/personal_dashboard";
import { InstrumentPanel } from "@/features/warrant_info/instrument_panel";
import {
  RegistryFilter,
  EMPTY_FILTER,
} from "@/components/common/registry_filter";
import { MARKET_COLOR, priceBandColor } from "@/components/common/grid_table";
import { columnOrder } from "@/components/common/watchlist_layout";

// This suite is about columns; the tape has its own tests.
vi.mock("@/data/query/use_fundamentals", () => ({
  useFundamentals: () => ({ data: null, quarters: [], isLoading: false, isError: false }),
}));
vi.mock("@/data/query/use_traded_log", () => ({
  useTradedLog: () => ({ items: [], sessionDate: null, sideBasis: null, isLoading: false, isError: false }),
}));

const fixture = vi.hoisted(() => {
  const items = [
    { symbol: "HPG", instrumentType: "STOCK" },
    { symbol: "CHPG2602", instrumentType: "CW", underlyingSymbol: "HPG" },
    { symbol: "VPB", instrumentType: "STOCK" },
    { symbol: "CVPB2615", instrumentType: "CW", underlyingSymbol: "VPB" },
  ];
  const quote = {
    symbol: "CHPG2602",
    lastPrice: 30,
    referencePrice: 40,
    ceilingPrice: 320,
    floorPrice: 10,
    bidPrice: 25,
    askPrice: 35,
    priceChange: -10,
    priceChangePercent: -0.25,
    tradedQuantity: 1234567 as number | null,
  };
  const specs = new Map([
    [
      "CHPG2602",
      {
        symbol: "CHPG2602",
        underlyingSymbol: "HPG",
        issuer: "ACBS",
        strikePrice: 25885,
        exerciseRatio: 3.57,
      },
    ],
    [
      "CVPB2615",
      {
        symbol: "CVPB2615",
        underlyingSymbol: "VPB",
        issuer: "TCBS",
        strikePrice: 28500,
        exerciseRatio: 2,
      },
    ],
  ]);
  // Per-test stock quotes; empty unless a test fills it.
  const stockQuotes = new Map<string, Record<string, unknown>>();
  return { items, quote, specs, stockQuotes };
});
vi.mock("@/data/watchlist", () => ({
  useWatchlist: () => ({
    items: fixture.items,
    isInWatchlist: () => true,
    addToWatchlist: vi.fn(),
    removeFromWatchlist: vi.fn(),
  }),
}));
vi.mock("@/data/use_research_market", () => ({
  useResearchMarket: () => ({
    quotes: new Map(),
    warrants: new Map(),
    marketSessionActive: false,
    isRealtimeTracked: () => true,
  }),
}));
vi.mock("@/data/instruments/use_instrument_specs", () => ({
  useInstrumentSpecs: () => ({
    getSpec: (symbol: string) => fixture.specs.get(symbol),
  }),
}));
vi.mock("@/data/query/use_dashboard_data", () => ({
  useDashboardData: () => ({
    meta: { marketSessionActive: false },
    getRow: (symbol: string) =>
      symbol === "CHPG2602"
        ? {
            quote: fixture.quote,
            analytics: { ivBid: 0.21, ivTrade: 0.23, ivAsk: 0.25, dte: 23 },
          }
        : fixture.stockQuotes.has(symbol)
          ? { quote: fixture.stockQuotes.get(symbol) }
          : undefined,
  }),
}));
vi.mock("@/data/query/use_market_overview", () => ({
  useMarketOverview: () => ({ isLoading: false, data: undefined }),
}));
vi.mock("@/data/query/use_stock_profiles", () => ({
  useStockProfiles: () => ({ profiles: [
    { symbol: "HPG", name: "Hoa Phat Group Joint Stock Company", short_name: "Hoa Phat", exchange: "HOSE" },
    { symbol: "VPB", name: "Vietnam Prosperity Joint Stock Commercial Bank", short_name: "VPBank", exchange: "HOSE" },
  ], isLoading: false, isError: false }),
}));
vi.mock("@/data/query", () => ({
  useHistoricalBars: () => ({ bars: [], isLoading: false }),
  useCorporateActions: () => ({ items: [], isLoading: false }),
}));

beforeEach(() => {
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      disconnect() {}
    },
  );
});
afterEach(() => {
  fixture.stockQuotes.clear();
  window.localStorage.clear();
  window.dispatchEvent(new StorageEvent("storage", { key: "cw-research:table-layout:v1" }));
  cleanup();
  vi.unstubAllGlobals();
});

describe("Targeted watchlist columns", () => {
  it("windows a large universe instead of mounting every market row", () => {
    const original = [...fixture.items];
    fixture.items.splice(0, fixture.items.length, ...Array.from({ length: 349 }, (_, index) => ({
      symbol: `CZZZ${String(index).padStart(4, "0")}`,
      instrumentType: "CW",
      underlyingSymbol: "HPG",
    })));
    try {
      const page = render(<PersonalDashboard />);
      const table = page.getByRole("table");
      expect(table.getAttribute("aria-rowcount")).toBe("350");
      expect(page.container.querySelectorAll("tbody tr[data-symbol]").length).toBeLessThan(60);
      expect(page.container.querySelectorAll(".watchlist-virtual-spacer")).toHaveLength(1);
    } finally {
      fixture.items.splice(0, fixture.items.length, ...original);
    }
  });

  it("sizes the windowed columns from fixed budgets, so scrolling cannot resize them", async () => {
    const original = [...fixture.items];
    fixture.items.splice(0, fixture.items.length, ...Array.from({ length: 349 }, (_, index) => ({
      symbol: `CZZZ${String(index).padStart(4, "0")}`,
      instrumentType: "CW",
      underlyingSymbol: "HPG",
    })));
    try {
      const page = render(<PersonalDashboard />);
      const table = page.getByRole("table");
      const cols = () => [...table.querySelectorAll("colgroup col")].map(col => (col as HTMLElement).style.width);
      const firstMounted = () => table.querySelector("tbody tr[data-symbol]")?.getAttribute("data-symbol");
      // One <col> per header cell (pin + 19 quote columns + dismiss), each with a width.
      expect(cols()).toHaveLength(table.querySelectorAll("thead th").length);
      expect(cols().every(Boolean)).toBe(true);
      // The quote headers carry no widths of their own: under table-layout: fixed the
      // colgroup is the only input (a `1%` th width would collapse a fixed column).
      expect([...table.querySelectorAll("thead th[data-column]")].every(th => !(th as HTMLElement).style.width)).toBe(true);
      const before = cols();
      expect(firstMounted()).toBe("CZZZ0000");

      const scroller = page.container.querySelector(".watchlist-table-scroll") as HTMLElement;
      Object.defineProperty(scroller, "scrollTop", { configurable: true, value: 6000 });
      fireEvent.scroll(scroller);
      await act(async () => { await new Promise(resolve => setTimeout(resolve, 50)); });

      expect(firstMounted()).not.toBe("CZZZ0000");
      expect(cols()).toEqual(before);
    } finally {
      fixture.items.splice(0, fixture.items.length, ...original);
    }
  });

  it("toggles the watchlist between all instruments, stocks only and CWs only", () => {
    const page = render(<PersonalDashboard />);
    const shown = () => [...page.container.querySelectorAll("tbody tr[data-symbol]")].map(row => row.getAttribute("data-symbol"));
    const group = page.getByRole("group", { name: "Show instruments" });
    const button = (name: string) => within(group).getByRole("button", { name });
    const pressed = () => within(group).getAllByRole("button").filter(b => b.getAttribute("aria-pressed") === "true").map(b => b.textContent);

    // Sits immediately left of FILTER ▾.
    expect(group.nextElementSibling?.querySelector(".filter-trigger")?.textContent).toBe("FILTER ▾");
    expect(pressed()).toEqual(["ALL"]);
    const all = shown();
    expect(all).toEqual(["HPG", "CHPG2602", "VPB", "CVPB2615"]);

    fireEvent.click(button("STOCK"));
    expect(pressed()).toEqual(["STOCK"]);
    expect(shown()).toEqual(["HPG", "VPB"]);
    expect(page.getByRole("table").getAttribute("aria-rowcount")).toBe("3");

    fireEvent.click(button("CW"));
    expect(pressed()).toEqual(["CW"]);
    expect(shown()).toEqual(["CHPG2602", "CVPB2615"]);

    fireEvent.click(button("ALL"));
    expect(shown()).toEqual(all);
  });

  it("shows a price board in the STOCK view instead of the warrant columns", () => {
    fixture.stockQuotes.set("HPG", {
      symbol: "HPG", referencePrice: 21000, ceilingPrice: 22450, floorPrice: 19550,
      lastPrice: 21100, tradedQuantity: 500, priceChange: 100, priceChangePercent: 0.0048,
      totalVolume: 9_460_100,
      bidPrice: 21050, bidQuantity: 120_000, bid2Price: 21000, bid2Quantity: 1_150_500,
      bid3Price: 20950, bid3Quantity: 300_000,
      askPrice: 21100, askQuantity: 90_000, ask2Price: 21150, ask2Quantity: 250_000,
      ask3Price: 21200, ask3Quantity: 779_000,
      highPrice: 21200, lowPrice: 20900,
      foreignBuy: 1_633_200, foreignSell: 470_100, foreignRoom: 2_292_162_142,
    });
    const page = render(<PersonalDashboard />);
    const labels = () => [...page.container.querySelectorAll("thead th[data-column]")].map(th => th.textContent);
    const hpg = () => {
      const cells = [...page.container.querySelectorAll<HTMLTableCellElement>("tr[data-symbol='HPG'] td")].slice(1);
      return Object.fromEntries(labels().map((label, i) => [label, cells[i]]));
    };
    const allLabels = labels();
    expect(allLabels).toContain("IV_BID");

    fireEvent.click(within(page.getByRole("group", { name: "Show instruments" })).getByRole("button", { name: "STOCK" }));
    expect(labels()).toEqual([
      "SYMBOL", "CEIL", "FLOOR", "REF",
      "BID_PRC_3", "BID_AMT_3", "BID_PRC_2", "BID_AMT_2", "BID_PRC_1", "BID_AMT_1",
      "TRD_PRC", "TRD_AMT", "+/-", "%CHG",
      "ASK_PRC_1", "ASK_AMT_1", "ASK_PRC_2", "ASK_AMT_2", "ASK_PRC_3", "ASK_AMT_3",
      "VOLUME", "HIGH", "LOW", "F_BUY", "F_SELL", "F_ROOM",
    ]);
    // One sized <col> per header, so the fixed layout covers every board column.
    expect(page.container.querySelectorAll("colgroup col[data-column]")).toHaveLength(26);
    const row = hpg();
    const text = (label: string) => row[label].textContent;
    expect(["BID_PRC_3", "BID_AMT_3", "BID_PRC_2", "BID_AMT_2", "BID_PRC_1", "BID_AMT_1"].map(text))
      .toEqual(["20,950", "300,000", "21,000", "1,150,500", "21,050", "120,000"]);
    expect(["ASK_PRC_1", "ASK_AMT_1", "ASK_PRC_2", "ASK_AMT_2", "ASK_PRC_3", "ASK_AMT_3"].map(text))
      .toEqual(["21,100", "90,000", "21,150", "250,000", "21,200", "779,000"]);
    expect(["VOLUME", "HIGH", "LOW", "F_BUY", "F_SELL", "F_ROOM"].map(text))
      .toEqual(["9,460,100", "21,200", "20,900", "1,633,200", "470,100", "2,292,162,142"]);
    // A depth size takes its own price's band: 21,000 is the reference, 21,200 is up.
    expect(row["BID_AMT_2"].style.color).toBe(MARKET_COLOR.flat);
    expect(row["ASK_AMT_3"].style.color).toBe(MARKET_COLOR.up);
    expect(row["BID_AMT_3"].style.color).toBe(MARKET_COLOR.down);

    fireEvent.click(within(page.getByRole("group", { name: "Show instruments" })).getByRole("button", { name: "ALL" }));
    expect(labels()).toEqual(allLabels);
  });

  it("keeps the STOCK view's column order separate and drops a sort it cannot show", () => {
    const page = render(<PersonalDashboard />);
    const labels = () => [...page.container.querySelectorAll("thead th[data-column]")].map(th => th.textContent);
    const header = (label: string) => [...page.container.querySelectorAll("thead th[data-column]")].find(th => th.textContent === label)!;
    const view = (name: string) => fireEvent.click(within(page.getByRole("group", { name: "Show instruments" })).getByRole("button", { name }));
    const allLabels = labels();

    fireEvent.click(header("IV_BID"));
    expect(header("IV_BID").getAttribute("aria-sort")).toBe("ascending");
    view("STOCK");
    expect(page.container.querySelector("thead th[aria-sort='ascending'], thead th[aria-sort='descending']")).toBeNull();

    fireEvent.keyDown(header("BID_PRC_3"), { key: "ArrowRight", altKey: true });
    expect(labels().slice(4, 6)).toEqual(["BID_AMT_3", "BID_PRC_3"]);
    const saved = JSON.parse(window.localStorage.getItem("cw-research:table-layout:v1")!);
    expect(saved.stockColumns.slice(4, 6)).toEqual(["bid3Qty", "bid3"]);

    view("ALL");
    expect(labels()).toEqual(allLabels);
    expect(header("IV_BID").getAttribute("aria-sort")).toBe("none");
  });

  it("keeps typing and suggestion selection separate from the submitted watchlist search", () => {
    const page = render(<PersonalDashboard />);
    const input = page.getByRole("combobox", { name: "Search watchlist symbols" });
    const order = () => [...page.container.querySelectorAll("tbody tr")].map(row => row.getAttribute("data-symbol"));
    const original = order();
    fireEvent.change(input, { target: { value: "VPB" } });
    expect(order()).toEqual(original);
    expect(page.container.querySelectorAll(".is-search-match")).toHaveLength(0);
    fireEvent.click(page.getAllByRole("option")[0]);
    expect(order()).toEqual(original);
    fireEvent.keyDown(input, { key: "Enter" });
    expect(order()).toEqual(["VPB", "CVPB2615", "HPG", "CHPG2602"]);
    expect(page.container.querySelectorAll(".is-search-match")).toHaveLength(2);
    fireEvent.change(input, { target: { value: "HPG" } });
    expect(order()[0]).toBe("VPB");
    fireEvent.keyDown(input, { key: "Enter" });
    expect(order()[0]).toBe("HPG");
    fireEvent.click(page.getByRole("button", { name: "Clear watchlist search" }));
    expect(order()).toEqual(original);
    expect(page.queryByRole("listbox")).toBeNull();
  });

  it("migrates the old amount column to last-match quantity", () => {
    const oldOrder = ["symbol", "ref", "last", "bid", "ivBid", "ask"];
    expect(columnOrder(oldOrder).slice(0, 7)).toEqual([
      "symbol", "ref", "last", "tradedQuantity", "bid", "ivBid", "ask",
    ]);
    expect(columnOrder(["tradingValue", ...oldOrder]).slice(0, 7)).toEqual([
      "tradedQuantity", ...oldOrder,
    ]);
  });

  // A non-positive last-match size means "no match observed", not a match of zero lots -
  // the provider can send MatchVolume 0 on a frame that matched nothing, and rendering a
  // literal "0" in the column was wrong.
  it.each([
    [1234567, "1,234,567"],
    [0, "—"],
    [null, "—"],
  ])("uses provider MatchVolume in both table and STATS: %s", (amount, expected) => {
    const original = fixture.quote.tradedQuantity;
    fixture.quote.tradedQuantity = amount;
    try {
      const page = render(<><PersonalDashboard /><InstrumentPanel instrument={{ symbol: "CHPG2602", instrumentType: "CW", quote: fixture.quote as any }} marketSessionActive={false} onClose={() => {}} /></>);
      const header = page.getByRole("columnheader", { name: "TRD_AMT" });
      const headers = page.getAllByRole("columnheader");
      const cells = within(page.getByText("CHPG2602", { selector: "td" }).closest("tr")!).getAllByRole("cell");
      expect(cells[headers.indexOf(header) + 1].textContent).toBe(expected);
      const stats = page.getByText("STATS").parentElement!;
      expect(within(stats).getByText("TRD_AMT").nextElementSibling?.textContent).toBe(expected);
      expect(within(stats).queryByText("ISSUER")).toBeNull();
      expect(header.title).toContain("most recent match");
    } finally {
      fixture.quote.tradedQuantity = original;
    }
  });

  it("pairs each IV with its matching price and keeps the CW symbol plain", () => {
    const page = render(<PersonalDashboard />);
    expect(
      page
        .getAllByRole("columnheader")
        .map((c) => c.textContent?.trim())
        .filter(Boolean),
    ).toEqual([
      "SYMBOL",
      "CEIL",
      "FLOOR",
      "REF",
      "IV_BID",
      "BID_PRC",
      "IV_TRD",
      "TRD_PRC",
      "TRD_AMT",
      "+/-",
      "%CHG",
      "IV_ASK",
      "ASK_PRC",
      "VOLUME",
      "STRIKE",
      "RATIO",
      "LAST_TRD_DATE",
      "DTE",
      "ISSUER",
    ]);
    const headers = page.getAllByRole("columnheader").map((cell) => cell.textContent);
    const rows = page.getAllByRole("row");
    const stockCells = within(rows.find((row) => row.textContent?.includes("HPG"))!).getAllByRole("cell");
    const cwCells = within(rows.find((row) => row.textContent?.includes("CHPG2602"))!).getAllByRole("cell");
    for (const key of ["IV_BID", "IV_TRD", "IV_ASK", "STRIKE", "RATIO", "LAST_TRD_DATE", "DTE", "ISSUER"]) {
      expect(stockCells[headers.indexOf(key) + 1].textContent).toBe("");
    }
    expect(cwCells[headers.indexOf("ISSUER") + 1].textContent).toBe("ACBS");
    const symbol = page.getByText("CHPG2602", { selector: "td" });
    expect(symbol.textContent).toBe("CHPG2602");
    const cells = within(symbol.closest("tr")!).getAllByRole("cell");
    expect(cells.slice(2, 14).map((c) => c.textContent)).toEqual([
      "320",
      "10",
      "40",
      "21.0%",
      "25",
      "23.0%",
      "30",
      "1,234,567",
      "10",
      "25.00%",
      "25.0%",
      "35",
    ]);
    expect(cells[2].style.color).toBe(MARKET_COLOR.ceiling);
    expect(cells[3].style.color).toBe(MARKET_COLOR.floor);
    expect(cells[4].style.color).toBe(MARKET_COLOR.flat);
    expect(
      within(
        page.getByText("HPG", { selector: "td" }).closest("tr")!,
      ).getAllByRole("cell")[4].style.color,
    ).toBe(MARKET_COLOR.null);
  });

  it("uses the same yellow reference value in Overview, with missing values grey", () => {
    const page = render(
      <InstrumentPanel
        instrument={{
          symbol: "CHPG2602",
          instrumentType: "CW",
          quote: fixture.quote as any,
        }}
        marketSessionActive={false}
        onClose={() => {}}
      />,
    );
    expect(page.getByText("40").style.color).toBe(MARKET_COLOR.flat);
    expect(priceBandColor(0, "reference")).toBe(MARKET_COLOR.flat);
    expect(priceBandColor(null, "reference")).toBe(MARKET_COLOR.null);
  });

  it("drags columns with their data and synchronizes STATS order", () => {
    const page = render(<><PersonalDashboard /><InstrumentPanel instrument={{ symbol: "CHPG2602", instrumentType: "CW", quote: fixture.quote as any }} marketSessionActive={false} onClose={() => {}} /></>);
    const transfer = { setData: vi.fn(), effectAllowed: "", dropEffect: "" };
    const from = page.getByRole("columnheader", { name: /^REF$/ });
    const to = page.getByRole("columnheader", { name: /^BID_PRC$/ });
    fireEvent.dragStart(from, { dataTransfer: transfer });
    fireEvent.dragOver(to, { dataTransfer: transfer });
    fireEvent.drop(to, { dataTransfer: transfer });
    const headers = page.getAllByRole("columnheader").map(c => c.textContent);
    expect(headers.indexOf("REF")).toBeGreaterThan(headers.indexOf("BID_PRC"));
    const cells = within(page.getByText("CHPG2602", { selector: "td" }).closest("tr")!).getAllByRole("cell");
    expect(cells[headers.indexOf("REF") + 1].textContent).toBe("40");
    expect(cells[headers.indexOf("BID_PRC") + 1].textContent).toBe("25");
    const stats = page.getByText("STATS").parentElement!;
    const labels = [...stats.children].slice(1).map(row => row.firstElementChild?.textContent);
    expect(labels.indexOf("REF")).toBeGreaterThan(labels.indexOf("BID_PRC"));
    expect(page.queryByText("AS OF")).toBeNull();
    fireEvent.keyDown(page.getByRole("columnheader", { name: /^REF$/ }), { key: "ArrowLeft", altKey: true });
    expect(page.getAllByRole("columnheader").map(c => c.textContent).indexOf("REF")).toBe(headers.indexOf("REF") - 1);
  });

  it("drags a stock with its children and prevents a CW from crossing groups", () => {
    fixture.items.push({ symbol: "CHPG2603", instrumentType: "CW", underlyingSymbol: "HPG" });
    try {
      const select = vi.fn();
      const page = render(<PersonalDashboard onSelectSymbol={select} />);
      const row = (symbol: string) => page.getByText(symbol, { selector: "td" }).closest("tr")!;
      const order = () => [...page.container.querySelectorAll("tbody tr")].map(r => r.getAttribute("data-symbol"));
      const drag = (from: string, to: string) => {
        const dataTransfer = { setData: vi.fn(), effectAllowed: "", dropEffect: "" };
        fireEvent.dragStart(row(from), { dataTransfer });
        fireEvent.dragOver(row(to), { dataTransfer });
        fireEvent.drop(row(to), { dataTransfer });
      };
      drag("HPG", "VPB");
      expect(order()).toEqual(["VPB", "CVPB2615", "HPG", "CHPG2602", "CHPG2603"]);
      drag("CHPG2603", "CHPG2602");
      expect(order()).toEqual(["VPB", "CVPB2615", "HPG", "CHPG2603", "CHPG2602"]);
      drag("CHPG2602", "CVPB2615");
      expect(order()).toEqual(["VPB", "CVPB2615", "HPG", "CHPG2603", "CHPG2602"]);
      expect(select).not.toHaveBeenCalled();
      fireEvent.click(row("CHPG2602"));
      expect(select).toHaveBeenCalledWith("CHPG2602");
    } finally { fixture.items.pop(); }
  });

  it("keeps the underlying choices available after a row is filtered out", () => {
    const page = render(<PersonalDashboard />);
    fireEvent.click(page.getByRole("button", { name: "FILTER ▾" }));
    fireEvent.click(page.getByRole("checkbox", { name: "HPG" }));
    expect(page.queryByText("CHPG2602", { selector: "td" })).toBeNull();
    expect(
      page.getByRole("checkbox", { name: "HPG" }),
    ).toBeTruthy();
    fireEvent.click(page.getByRole("checkbox", { name: "HPG" }));
    expect(page.getByText("CHPG2602", { selector: "td" })).toBeTruthy();
  });
});

function FilterHarness() {
  const [value, setValue] = useState(EMPTY_FILTER);
  return (
    <>
      <button>Outside</button>
      <RegistryFilter
        underlyingOptions={Array.from({ length: 24 }, (_, i) => `SYM${i}`)}
        issuerOptions={["ACBS", "SSI", "TCBS"]}
        value={value}
        onChange={setValue}
      />
    </>
  );
}

describe("Filter and nested calendar interaction", () => {
  it("clears an unfinished typed date even when no date filter was committed", () => {
    const page = render(<FilterHarness />);
    fireEvent.click(page.getByRole("button", { name: "FILTER ▾" }));
    const field = page.getByRole("textbox", { name: "Last trading date from" }) as HTMLInputElement;
    fireEvent.change(field, { target: { value: "09" } });
    fireEvent.blur(field);
    expect(field.value).toBe("09");
    fireEvent.click(page.getByRole("button", { name: "CLEAR" }));
    expect(field.value).toBe("");
    expect(page.queryByRole("alert")).toBeNull();
  });

  it("keeps filters open through month navigation and date selection; Escape closes only the calendar first", () => {
    const page = render(<FilterHarness />);
    fireEvent.click(page.getByRole("button", { name: "FILTER ▾" }));
    expect(
      page.getByRole("textbox", { name: "Filter by underlying symbol" }),
    ).toBe(document.activeElement);
    fireEvent.click(
      page.getByRole("button", {
        name: "Last trading date to — open calendar",
      }),
    );
    fireEvent.click(page.getByRole("button", { name: "Next month" }));
    expect(
      page.getByRole("dialog", { name: "Instrument filters" }),
    ).toBeTruthy();
    fireEvent.keyDown(page.getByRole("button", { name: "Next month" }), {
      key: "Escape",
    });
    expect(
      page.queryByRole("dialog", { name: "Last trading date to calendar" }),
    ).toBeNull();
    expect(
      page.getByRole("dialog", { name: "Instrument filters" }),
    ).toBeTruthy();
    fireEvent.click(
      page.getByRole("button", {
        name: "Last trading date to — open calendar",
      }),
    );
    const day = page
      .getAllByRole("button")
      .find((b) =>
        /^\d{4}-\d{2}-15$/.test(b.getAttribute("aria-label") ?? ""),
      )!;
    fireEvent.click(day);
    expect(
      (
        page.getByRole("textbox", {
          name: "Last trading date to",
        }) as HTMLInputElement
      ).value,
    ).toMatch(/^\d{2}\/15\/\d{4}$/);
    fireEvent.click(page.getByRole("button", { name: "CLEAR" }));
    expect(
      (
        page.getByRole("textbox", {
          name: "Last trading date to",
        }) as HTMLInputElement
      ).value,
    ).toBe("");
    fireEvent.keyDown(
      page.getByRole("textbox", { name: "Last trading date to" }),
      { key: "Escape" },
    );
    expect(page.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(
      page.getByRole("button", { name: "FILTER ▾" }),
    );
  });

  it("lets a long list be searched and dismissed by clicking outside", () => {
    const page = render(<FilterHarness />);
    fireEvent.click(page.getByRole("button", { name: "FILTER ▾" }));
    expect(page.getAllByRole("checkbox")).toHaveLength(29);
    fireEvent.change(
      page.getByRole("textbox", { name: "Filter by underlying symbol" }),
      { target: { value: "SYM23" } },
    );
    expect(page.getByRole("checkbox", { name: "SYM23" })).toBeTruthy();
    expect(
      page.queryByRole("checkbox", { name: "SYM0" }),
    ).toBeNull();
    fireEvent.pointerDown(page.getByRole("button", { name: "Outside" }));
    expect(page.queryByRole("dialog")).toBeNull();
  });
});
