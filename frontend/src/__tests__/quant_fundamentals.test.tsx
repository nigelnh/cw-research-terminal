// @vitest-environment happy-dom
/**
 * QUANT tab fundamentals.
 *
 * Financial statement and ratio fields keep their reporting period and remain explicitly
 * unavailable when the upstream dataset omits them.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render } from "@testing-library/react";

const corpActions = vi.hoisted(() => ({ items: [] as any[], isLoading: false, isError: false }));
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
    useCorporateActions: () => corpActions,
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
  corpActions.items = [];
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

// --------------------------------------------------------------------------- #
describe("Quarter-on-quarter context", () => {
  const withSeries = () => {
    fundamentals.data = {
      pe: 12.23, pb: 3.08, valuation_as_of: "2026-09-04",
      eps: 1507, roe: .2647, roa: .1278, roic: .167,
      gross_margin: .347, net_margin: .172, latest_period: "2026Q2",
      unavailable: {}, provenance: {},
    };
    fundamentals.quarters = [
      { period: "2026Q1", eps: 1400, roe: .2500, roa: .1200, roic: .1600,
        gross_margin: .3400, net_margin: .1700, revenue: 1, net_profit: 1 },
      { period: "2026Q2", eps: 1507, roe: .2647, roa: .1278, roic: .1670,
        gross_margin: .3470, net_margin: .1720, revenue: 1, net_profit: 1 },
    ];
  };

  it("says which way the statement metrics moved last quarter", () => {
    // Eight bare numbers said where the company is and nothing about where it is going,
    // while the series needed to say so was already on screen in the chart beside them.
    withSeries();
    const text = quantTab().container.textContent ?? "";
    expect(text).toContain("\u25B2107");   // EPS 1400 -> 1507 VND
    expect(text).toContain("\u25B21.5pp"); // ROE 25.00% -> 26.47%
    expect(text).toContain("\u25B20.8pp"); // ROA 12.00% -> 12.78%
  });

  it("gives PE and PB no delta, because there is no series behind them", () => {
    // They come from a trailing valuation snapshot. A quarter-on-quarter figure for them
    // would be invented, and this panel does not invent numbers.
    withSeries();
    const view = quantTab();
    const pe = view.getByText("PE").closest("div")?.textContent ?? "";
    const pb = view.getByText("PB").closest("div")?.textContent ?? "";
    for (const cell of [pe, pb]) {
      expect(cell).not.toContain("\u25B2");
      expect(cell).not.toContain("\u25BC");
    }
  });

  it("stays silent when there is only one quarter to go on", () => {
    withSeries();
    fundamentals.quarters = [fundamentals.quarters[1]];
    const text = quantTab().container.textContent ?? "";
    expect(text).not.toContain("\u25B2");
    expect(text).not.toContain("\u25BC");
  });
});

// --------------------------------------------------------------------------- #
describe("CORPORATE EVENTS", () => {
  const event = (over: Record<string, unknown>) => ({
    id: 1, symbol: "HPG", event_label: "New listing", action_type: "ADDITIONAL_LISTING",
    event_type: "ADDITIONAL_LISTING", event_class: "LISTING", status: "CONFIRMED",
    ex_date: null, record_date: null, payment_date: null, disclosure_date: null,
    public_date: null, cash_amount_vnd: null, ratio_pct: null, ratio_text: null,
    dividend_year: null, note: null, note_en: null, source: "VNDIRECT", ...over,
  });

  it("labels the date column for every event, not just dividends", () => {
    // It read EX-DIV. A listing and a financial statement have no ex-dividend date, and
    // those are most of the rows.
    corpActions.items = [event({ ex_date: "2036-06-24", public_date: "2026-08-20" })];
    const text = quantTab().container.textContent ?? "";
    expect(text).toContain("DISCLOSED");
    expect(text).toContain("EX-DATE");
    expect(text).not.toContain("EX-DIV");
  });

  it("shows the disclosure date the list is ordered by", () => {
    corpActions.items = [event({ ex_date: "2036-06-24", public_date: "2026-08-20" })];
    const text = quantTab().container.textContent ?? "";
    expect(text).toContain("2026-08-20");   // when the market learned of it
    expect(text).toContain("2036-06-24");   // the vesting date, still on the row
  });

  it("renders the English note instead of a dash on every row", () => {
    // 0 of 12 FPT events carried `cash_amount_vnd` or `ratio_text`, so DESC was a dash
    // for all of them while the substance sat in the Vietnamese `note`.
    corpActions.items = [event({ note: "Số lượng 2,302,000 CP", note_en: "2,302,000 shares" })];
    expect(quantTab().container.textContent ?? "").toContain("2,302,000 shares");
  });

  it("never renders the raw Vietnamese note", () => {
    // Out of pattern upstream, so the backend declined to translate it. A dash is the
    // honest answer; the original must not leak through as a fallback.
    corpActions.items = [event({ note: "Công ty Cổ phần FPT (FPT) niêm yết bổ sung", note_en: null })];
    expect(quantTab().container.textContent ?? "").not.toContain("Công ty");
  });
});
