// @vitest-environment happy-dom
/**
 * QUANT tab fundamentals.
 *
 * Financial statement and ratio fields keep their reporting period and remain explicitly
 * unavailable when the upstream dataset omits them.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render } from "@testing-library/react";

const fundamentals = vi.hoisted(() => ({
  data: null as any,
  quarters: [] as any[],
  isLoading: false,
  isError: false,
}));
vi.mock("@/data/query/use_fundamentals", () => ({ useFundamentals: () => fundamentals }));
vi.mock("@/data/query/use_traded_log", () => ({
  useTradedLog: () => ({ items: [], sessionDate: null, sideBasis: null, isLoading: false, isError: false }),
}));
vi.mock("react-chartjs-2", () => ({
  Bar: (props: any) => <div data-testid="bar" data-labels={JSON.stringify(props.data.labels)} />,
  Scatter: () => null,
}));
vi.mock("@/data/query", async (orig) => {
  const actual = (await orig()) as Record<string, unknown>;
  return {
    ...actual,
    useHistoricalBars: () => ({ bars: [], isLoading: false, isFetching: false, isError: false, isEmpty: true, refetch: () => {} }),
    useCorporateActions: () => ({ items: [], isLoading: false, isError: false }),
  };
});

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { InstrumentPanel } from "@/features/warrant_info/instrument_panel";

const stock = { symbol: "HPG", instrumentType: "STOCK" as const };

function quantTab() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(
    <QueryClientProvider client={qc}>
      <InstrumentPanel instrument={stock as never} marketSessionActive={false} onClose={() => {}} />
    </QueryClientProvider>,
  );
  // `initialTab` is reset to "overview" by the panel's on-symbol effect, so open the tab
  // the way a user does. That is the more faithful path anyway.
  fireEvent.click(view.getByRole("button", { name: "QUANT" }));
  return view;
}

const row = (period: string, revenue: number, profit: number) => ({
  period, revenue, net_profit: profit, ebit: profit * 1.2,
  net_margin: profit / revenue,
});

afterEach(() => {
  cleanup();
  fundamentals.data = null;
  fundamentals.quarters = [];
  fundamentals.isLoading = false;
  fundamentals.isError = false;
});

describe("FINANCIAL INDICATORS", () => {
  it("shows the figures this tier actually serves", () => {
    fundamentals.data = {
      pe: 7.89115654, pb: 1.30068952, valuation_as_of: "2026-09-04",
      eps: 1781, roe: .1738, roa: .0891, roic: .1072,
      gross_margin: .1644, net_margin: 0.11467485, latest_period: "2026Q2",
      unavailable: {},
      provenance: {
        eps: { source: "VNSTOCK_VCI_INCOME_STATEMENT", as_of: "2026Q2" },
        roe: { source: "VNSTOCK_VCI_RATIO_SUMMARY", as_of: "2026Q2" },
      },
    };
    const text = quantTab().container.textContent ?? "";
    expect(text).toContain("1,781 VND");
    expect(text).toContain("7.89");   // PE, 2dp
    expect(text).toContain("1.30");   // PB
    expect(text).toContain("17.4%");  // ROE
    expect(text).toContain("8.9%");   // ROA
    expect(text).toContain("10.7%");  // ROIC
    expect(text).toContain("16.4%");  // gross margin
    expect(text).toContain("11.5%");  // net margin, derived from profit / revenue
  });

  it("keeps the unavailable rows visible with a stated reason", () => {
    fundamentals.data = {
      pe: null, pb: null, valuation_as_of: null, eps: null, roe: null, roa: null,
      roic: null, gross_margin: null, net_margin: null, latest_period: null,
      unavailable: {
        eps: "not served by the current market-data source",
        roe: "not served by the current market-data source",
        roa: "not served by the current market-data source",
        roic: "not served by the current market-data source",
        gross_margin: "not served by the current market-data source",
      },
      provenance: {},
    };
    const view = quantTab();
    for (const label of ["EPS", "ROE", "ROA", "ROIC", "GROSS MARGIN"]) {
      const el = view.getByText(label).closest("[title]") as HTMLElement | null;
      expect(el, `${label} should explain itself`).not.toBeNull();
      expect(el!.title).toMatch(/not served by the current market-data source/i);
    }
  });

  it("dates the valuation so a stale P/E is never read as today's", () => {
    fundamentals.data = { pe: 7.89, pb: 1.3, valuation_as_of: "2026-09-04", net_margin: null, latest_period: null };
    const el = quantTab().getByText("PE").closest("[title]") as HTMLElement;
    expect(el.title).toContain("2026-09-04");
  });

  it("renders an em dash, never a zero, when a figure is missing", () => {
    fundamentals.data = { pe: null, pb: null, valuation_as_of: null, net_margin: null, latest_period: null };
    const view = quantTab();
    const pe = view.getByText("PE").parentElement?.textContent ?? "";
    expect(pe).toContain("—");
    expect(pe).not.toContain("0.00");
  });
});

describe("REVENUE & PROFIT chart", () => {
  it("plots the reported quarters in order", () => {
    fundamentals.quarters = [
      row("2025Q4", 47_301_623_136_340, 3_860_994_446_656),
      row("2026Q1", 53_312_910_120_686, 8_994_003_244_142),
      row("2026Q2", 55_557_246_173_846, 6_371_019_004_563),
    ];
    const chart = quantTab().getByTestId("bar");
    expect(JSON.parse(chart.dataset.labels!)).toEqual(["2025Q4", "2026Q1", "2026Q2"]);
  });

  it("says plainly when there are no statements rather than drawing an empty axis", () => {
    const view = quantTab();
    expect(view.container.textContent).toContain("No quarterly statements for this symbol.");
    expect(view.queryByTestId("bar")).toBeNull();
  });

  it("distinguishes a failed read from an empty one", () => {
    fundamentals.isError = true;
    expect(quantTab().container.textContent).toContain("Financial statements unavailable.");
  });
});
