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
    priceChangePercent: -0.25,
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
  cleanup();
  vi.unstubAllGlobals();
});

describe("Targeted watchlist columns", () => {
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
      "IV BID",
      "BID",
      "IV TRD",
      "TRD",
      "+/-",
      "%CHG",
      "IV ASK",
      "ASK",
      "VOLUME",
      "STRIKE",
      "RATIO",
      "DTE",
    ]);
    const symbol = page.getByText("CHPG2602", { selector: "td" });
    expect(symbol.textContent).toBe("CHPG2602");
    const cells = within(symbol.closest("tr")!).getAllByRole("cell");
    expect(cells.slice(2, 13).map((c) => c.textContent)).toEqual([
      "320",
      "10",
      "40",
      "21.0%",
      "25",
      "23.0%",
      "30",
      "10",
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
