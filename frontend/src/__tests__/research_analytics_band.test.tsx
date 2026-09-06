// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { renderHook } from "@testing-library/react";

/**
 * The band's data contract. chart.js needs a real canvas, which happy-dom does not
 * provide, so `react-chartjs-2` is stubbed into inspectable markup: every assertion here
 * is about the DATA handed to each chart, which is the part that can silently be wrong.
 */
const charts = vi.hoisted(() => ({ scatter: [] as any[], bar: [] as any[] }));
vi.mock("react-chartjs-2", () => ({
  Scatter: (props: any) => {
    charts.scatter.push(props);
    return <div data-testid="scatter" />;
  },
  Bar: (props: any) => {
    charts.bar.push(props);
    return <div data-testid="bar" />;
  },
}));

const state = vi.hoisted(() => ({
  rows: new Map<string, any>(),
  specs: new Map<string, any>(),
  meta: { asOf: "2026-09-04T15:00:00+07:00", marketSessionActive: false },
  isLoading: false,
  isError: false,
}));

vi.mock("@/data/query/use_dashboard_data", () => ({
  useDashboardData: () => ({
    getRow: (s: string) => state.rows.get(s.toUpperCase()),
    meta: { ...state.meta, marketSession: "CLOSED", latestCompletedSession: null, calendarConfidence: null },
    isLoading: state.isLoading,
    isError: state.isError,
    refetch: () => {},
  }),
}));
vi.mock("@/data/instruments/use_instrument_specs", () => ({
  useInstrumentSpecs: () => ({
    getSpec: (s: string | null) => (s ? (state.specs.get(s.toUpperCase()) ?? null) : null),
    specs: state.specs,
    isLoading: false,
    isError: false,
  }),
}));

import { useUniverseAnalytics } from "@/data/query/use_universe_analytics";
import { ResearchAnalyticsBand } from "@/features/stock_research/research_analytics_band";

function cw(symbol: string, underlying: string, maturity: string) {
  state.specs.set(symbol, {
    symbol, instrumentType: "CW", underlyingSymbol: underlying,
    issuer: "HCM", maturityDate: maturity, strikePrice: 1, exerciseRatio: 1,
  });
}
function analytics(symbol: string, o: { mk: number; iv: number; hv: number; dte: number; value?: number }) {
  state.rows.set(symbol, {
    symbol,
    quote: { tradingValue: o.value ?? 1000 },
    analytics: {
      isAvailable: true, moneynessRatio: o.mk, ivMid: o.iv,
      historicalVolatility: o.hv, dte: o.dte, moneynessCategory: o.mk >= 1 ? "ITM" : "OTM",
    },
  });
}

function reset() {
  state.rows.clear();
  state.specs.clear();
  state.isLoading = false;
  state.isError = false;
  charts.scatter.length = 0;
  charts.bar.length = 0;
}

afterEach(() => { cleanup(); reset(); });

describe("useUniverseAnalytics — joins quotes, analytics and the registry", () => {
  it("keeps CWs with available analytics and derives the IV−HV spread in points", () => {
    reset();
    cw("CHPG2627", "HPG", "2027-03-16");
    analytics("CHPG2627", { mk: 0.9234, iv: 0.448122, hv: 0.2494, dte: 193 });

    const { result } = renderHook(() => useUniverseAnalytics(["CHPG2627"]));
    expect(result.current.points).toHaveLength(1);
    const p = result.current.points[0];
    expect(p.underlying).toBe("HPG");
    expect(p.maturityMonth).toBe("2027-03");
    // 44.8122% - 24.94% = 19.87pp
    expect(p.spreadPp).toBeCloseTo(19.8722, 3);
    expect(result.current.basis).toBe("LAST_SESSION");
  });

  it("excludes stocks, and CWs whose analytics did not resolve", () => {
    reset();
    cw("CHPG2627", "HPG", "2027-03-16");
    analytics("CHPG2627", { mk: 0.92, iv: 0.44, hv: 0.25, dte: 193 });
    cw("CHPG2618", "HPG", "2026-12-28");
    state.rows.set("CHPG2618", { symbol: "CHPG2618", quote: {}, analytics: { isAvailable: false } });
    state.specs.set("HPG", { symbol: "HPG", instrumentType: "STOCK", underlyingSymbol: null, maturityDate: null });
    state.rows.set("HPG", { symbol: "HPG", quote: { tradingValue: 9 }, analytics: null });

    const { result } = renderHook(() => useUniverseAnalytics(["HPG", "CHPG2627", "CHPG2618"]));
    expect(result.current.points.map(p => p.symbol)).toEqual(["CHPG2627"]);
    // both warrants are counted as CWs even though only one plots
    expect(result.current.cwCount).toBe(2);
  });

  it("reports the distinct underlyings in sorted order", () => {
    reset();
    cw("CVPB2615", "VPB", "2027-02-15"); analytics("CVPB2615", { mk: 0.97, iv: 0.225, hv: 0.287, dte: 166 });
    cw("CFPT2616", "FPT", "2026-10-28"); analytics("CFPT2616", { mk: 0.88, iv: 0.807, hv: 0.309, dte: 54 });
    cw("CHPG2627", "HPG", "2027-03-16"); analytics("CHPG2627", { mk: 0.92, iv: 0.448, hv: 0.249, dte: 193 });

    const { result } = renderHook(() => useUniverseAnalytics(["CVPB2615", "CFPT2616", "CHPG2627"]));
    expect(result.current.underlyings).toEqual(["FPT", "HPG", "VPB"]);
  });

  it("a negative spread survives — a warrant can price BELOW realized vol", () => {
    reset();
    cw("CVPB2615", "VPB", "2027-02-15");
    analytics("CVPB2615", { mk: 0.9754, iv: 0.225, hv: 0.287, dte: 166 });
    const { result } = renderHook(() => useUniverseAnalytics(["CVPB2615"]));
    expect(result.current.points[0].spreadPp).toBeCloseTo(-6.2, 5);
  });
});

describe("ResearchAnalyticsBand — the three cards", () => {
  const seed = () => {
    reset();
    cw("CFPT2616", "FPT", "2026-10-28"); analytics("CFPT2616", { mk: 0.8829, iv: 0.807, hv: 0.309, dte: 54 });
    cw("CFPT2626", "FPT", "2027-04-02"); analytics("CFPT2626", { mk: 0.9772, iv: 0.328, hv: 0.309, dte: 210 });
    cw("CHPG2627", "HPG", "2027-03-16"); analytics("CHPG2627", { mk: 0.9234, iv: 0.448, hv: 0.249, dte: 193 });
    cw("CVPB2615", "VPB", "2027-02-15"); analytics("CVPB2615", { mk: 0.9754, iv: 0.225, hv: 0.287, dte: 166 });
  };

  it("renders all three cards", () => {
    seed();
    render(<ResearchAnalyticsBand symbols={["CFPT2616", "CFPT2626", "CHPG2627", "CVPB2615"]} />);
    expect(screen.getByLabelText("VOLATILITY SKEW")).toBeTruthy();
    expect(screen.getByLabelText("RICH / CHEAP")).toBeTruthy();
    expect(screen.getByLabelText("MATURITY LADDER")).toBeTruthy();
  });

  it("skew: one point series per underlying, plus a single ATM reference", () => {
    seed();
    render(<ResearchAnalyticsBand symbols={["CFPT2616", "CFPT2626", "CHPG2627", "CVPB2615"]} />);
    const sets = charts.scatter[charts.scatter.length - 1].data.datasets;
    const pointSets = sets.filter((d: any) => d.label !== "__atm");
    const atm = sets.filter((d: any) => d.label === "__atm");
    expect(pointSets.map((d: any) => d.label)).toEqual(["FPT", "HPG", "VPB"]);
    // exactly one reference line, vertical at S/K = 1.00
    expect(atm).toHaveLength(1);
    expect(atm[0].data.map((d: any) => d.x)).toEqual([1, 1]);
    expect(atm[0].borderDash).toBeTruthy();
    // FPT holds two warrants; IV is plotted as a percentage, not a decimal
    expect(pointSets[0].data).toHaveLength(2);
    expect(pointSets[0].data[0].y).toBeCloseTo(80.7, 4);
    expect(pointSets[0].data[0].sym).toBe("CFPT2616");
  });

  it("skew: the y axis fits the data instead of anchoring at zero", () => {
    seed();
    render(<ResearchAnalyticsBand symbols={["CFPT2616", "CFPT2626", "CHPG2627", "CVPB2615"]} />);
    const y = charts.scatter[charts.scatter.length - 1].options.scales.y;
    // IVs run 22.5% .. 80.7%; a 0-100 axis would spend half the card on empty space
    expect(y.min).toBeGreaterThan(0);
    expect(y.min).toBeLessThan(22.5);
    expect(y.max).toBeGreaterThan(80.7);
    expect(y.max).toBeLessThan(100);
  });

  it("skew: each underlying's realized vol is reported in the legend", () => {
    seed();
    render(<ResearchAnalyticsBand symbols={["CFPT2616", "CFPT2626", "CHPG2627", "CVPB2615"]} />);
    const skew = screen.getByLabelText("VOLATILITY SKEW");
    expect(skew.textContent).toContain("HV 30.9%");
    expect(skew.textContent).toContain("HV 24.9%");
    expect(skew.textContent).toContain("HV 28.7%");
  });

  it("rich/cheap: sorted richest-first and colored by the sign of the spread", () => {
    seed();
    render(<ResearchAnalyticsBand symbols={["CFPT2616", "CFPT2626", "CHPG2627", "CVPB2615"]} />);
    const spread = charts.bar.find(c => c.options?.indexAxis === "y");
    // CFPT2616 +49.8, CHPG2627 +19.9, CFPT2626 +1.9, CVPB2615 -6.2
    expect(spread.data.labels).toEqual(["CFPT2616", "CHPG2627", "CFPT2626", "CVPB2615"]);
    const colors = spread.data.datasets[0].backgroundColor;
    expect(colors[0]).toBe(colors[1]); // both rich
    expect(colors[3]).not.toBe(colors[0]); // the cheap one is the other color
  });

  it("maturity ladder: one bucket per month, stacked by underlying", () => {
    seed();
    render(<ResearchAnalyticsBand symbols={["CFPT2616", "CFPT2626", "CHPG2627", "CVPB2615"]} />);
    const ladder = charts.bar.find(c => c.options?.scales?.x?.stacked);
    expect(ladder.data.labels).toEqual(["2026-10", "2027-02", "2027-03", "2027-04"]);
    const fpt = ladder.data.datasets.find((d: any) => d.label === "FPT");
    // FPT expires once in 2026-10 and once in 2027-04, nothing in between
    expect(fpt.data).toEqual([1, 0, 0, 1]);
  });

  it("shows an honest empty state rather than an axis with no data", () => {
    reset();
    state.specs.set("HPG", { symbol: "HPG", instrumentType: "STOCK", underlyingSymbol: null, maturityDate: null });
    state.rows.set("HPG", { symbol: "HPG", quote: {}, analytics: null });
    render(<ResearchAnalyticsBand symbols={["HPG"]} />);
    expect(screen.getAllByText("NO WARRANTS ON THE WATCHLIST").length).toBe(3);
    expect(screen.queryByTestId("scatter")).toBeNull();
  });

  it("distinguishes 'no warrants' from 'warrants but no analytics this session'", () => {
    reset();
    cw("CHPG2618", "HPG", "2026-12-28");
    state.rows.set("CHPG2618", { symbol: "CHPG2618", quote: {}, analytics: { isAvailable: false } });
    render(<ResearchAnalyticsBand symbols={["CHPG2618"]} />);
    expect(screen.getAllByText("NO ANALYTICS FOR THIS SESSION").length).toBe(3);
  });
});
