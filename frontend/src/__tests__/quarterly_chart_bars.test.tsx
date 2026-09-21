// @vitest-environment happy-dom
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { QuarterlyResultsChart } from "@/features/warrant_info/quarterly_results_chart";

// Captures what the component hands chart.js, which is where all three defects lived.
const captured = vi.hoisted(() => ({ data: null as any, options: null as any }));
vi.mock("react-chartjs-2", () => ({
  Bar: (props: any) => {
    captured.data = props.data;
    captured.options = props.options;
    return <div data-testid="bar" />;
  },
}));

afterEach(cleanup);

const ROWS = [
  { period: "2025Q3", revenue: 17_000e9, net_profit: 2_400e9, ebit: null, net_margin: null },
  { period: "2025Q4", revenue: 20_200e9, net_profit: 2_550e9, ebit: null, net_margin: null },
  { period: "2026Q1", revenue: 12_800e9, net_profit: 2_520e9, ebit: null, net_margin: null },
  { period: "2026Q2", revenue: 14_100e9, net_profit: 2_600e9, ebit: null, net_margin: null },
];

function renderChart() {
  render(<QuarterlyResultsChart rows={ROWS} isLoading={false} isError={false} />);
  return captured.data.datasets as any[];
}

describe("Quarterly results bars", () => {
  it("states a hover colour, so a hovered bar does not fall back to chart.js black", () => {
    // chart.js 4.x leaves `hoverBackgroundColor` undefined and resolves it to the global
    // `backgroundColor` default, rgba(0,0,0,0.1). On this dark ground the hovered Net
    // profit bar turned black and read as a render failure.
    for (const ds of renderChart()) {
      expect(ds.hoverBackgroundColor, `${ds.label} has no hover colour`).toBeTruthy();
      expect(ds.hoverBackgroundColor).toEqual(ds.backgroundColor);
    }
  });

  it("gives both series the same bar thickness", () => {
    // Revenue was 26px against Net profit's 14px. They are peers on their own axes, so
    // the split read as one series being half-rendered rather than as a hierarchy.
    const [revenue, profit] = renderChart();
    expect(revenue.maxBarThickness).toBe(profit.maxBarThickness);
  });

  it("fills the category instead of leaving a four-quarter panel mostly air", () => {
    // These are DATASET options in chart.js v4. Setting them on the chart silently does
    // nothing, which is how the spacing looked untouched before.
    for (const ds of renderChart()) {
      expect(ds.categoryPercentage).toBeGreaterThan(0.7);
      expect(ds.barPercentage).toBeGreaterThan(0.8);
    }
  });
});
