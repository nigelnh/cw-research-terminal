// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, within } from "@testing-library/react";
import { useState } from "react";
import { PersonalDashboard } from "@/features/watchlist/personal_dashboard";
import { InstrumentPanel } from "@/features/warrant_info/instrument_panel";
import {
  RegistryFilter,
  EMPTY_FILTER,
} from "@/components/common/registry_filter";
import { MARKET_COLOR, priceBandColor } from "@/components/common/grid_table";
import { columnOrder } from "@/components/common/watchlist_layout";

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
    tradingValue: 987654321 as number | null,
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
  return { items, quote, specs };
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
  window.localStorage.clear();
  window.dispatchEvent(new StorageEvent("storage", { key: "cw-research:table-layout:v1" }));
  cleanup();
  vi.unstubAllGlobals();
});

describe("Targeted watchlist columns", () => {
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

  it("migrates the saved TRD_AMT column id and keeps it beside trade price", () => {
    const oldOrder = ["symbol", "ref", "last", "bid", "ivBid", "ask"];
    expect(columnOrder(oldOrder).slice(0, 7)).toEqual([
      "symbol", "ref", "last", "tradingValue", "bid", "ivBid", "ask",
    ]);
    // a saved layout that still names the old id resolves to the value column
    expect(columnOrder(["tradedQuantity", ...oldOrder]).slice(0, 7)).toEqual([
      "tradingValue", ...oldOrder,
    ]);
  });

  it.each([987654321, 0, null])("shows session traded value in the table and STATS: %s", (amount) => {
    const original = fixture.quote.tradingValue;
    fixture.quote.tradingValue = amount;
    try {
      const page = render(<><PersonalDashboard /><InstrumentPanel instrument={{ symbol: "CHPG2602", instrumentType: "CW", quote: fixture.quote as any }} marketSessionActive={false} onClose={() => {}} /></>);
      const expected = !amount ? "—" : "987.7M";
      const header = page.getByRole("columnheader", { name: "TRD_AMT" });
      const headers = page.getAllByRole("columnheader");
      const cells = within(page.getByText("CHPG2602", { selector: "td" }).closest("tr")!).getAllByRole("cell");
      expect(cells[headers.indexOf(header) + 1].textContent).toBe(expected);
      const stats = page.getByText("STATS").parentElement!;
      expect(within(stats).getByText("TRD_AMT").nextElementSibling?.textContent).toBe(expected);
      expect(within(stats).queryByText("ISSUER")).toBeNull();
      expect(header.title).toContain("turnover");
    } finally {
      fixture.quote.tradingValue = original;
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
      "987.7M",
      "−10",
      "-25.00%",
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
