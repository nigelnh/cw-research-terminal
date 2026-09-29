// @vitest-environment happy-dom
import type { ReactElement } from "react";
import { act, cleanup, fireEvent, render as rtlRender } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { HistoricalBar } from "@/domain/models";

const requests = vi.hoisted(() => ({ calls: [] as Record<string, unknown>[] }));

/** Weekday daily bars from 2026-01-05, enough for several weeks and months. */
const DAILY: HistoricalBar[] = (() => {
  const out: HistoricalBar[] = [];
  const d = new Date("2026-01-05T00:00:00Z");
  while (out.length < 120) {
    if (d.getUTCDay() !== 0 && d.getUTCDay() !== 6) {
      const iso = d.toISOString().slice(0, 10);
      const k = out.length + 1;
      out.push({ symbol: "HPG", date: iso, sessionDate: iso, open: k, high: k + 1, low: k - 1, close: k, volume: 100 });
    }
    d.setUTCDate(d.getUTCDate() + 1);
  }
  return out;
})();

vi.mock("@/data/query", () => ({
  useHistoricalBars: (args: Record<string, unknown>) => {
    requests.calls.push(args);
    return { bars: DAILY, isLoading: false, isEmpty: false, isFetching: false, isError: false, error: null, refetch: () => {} };
  },
  useCorporateActions: () => ({ items: [], isLoading: false, isError: false }),
}));
vi.mock("@/data/query/use_fundamentals", () => ({
  useFundamentals: () => ({ data: null, quarters: [], isLoading: false, isError: false }),
}));
vi.mock("@/data/query/use_traded_log", () => ({
  useTradedLog: () => ({ items: [], sessionDate: null, sideBasis: null, isLoading: false, isError: false }),
}));
vi.mock("@/components/common/trading_chart", () => ({
  TradingChart: (props: { interval: string; bars: HistoricalBar[] }) => (
    <div
      data-testid="chart" data-interval={props.interval} data-bars={props.bars.length}
      data-first={props.bars[0]?.date} data-last-close={props.bars[props.bars.length - 1]?.close}
    />
  ),
}));

import { InstrumentPanel } from "@/features/warrant_info/instrument_panel";
import { AiChatProvider } from "@/data/ai/ai_chat_provider";

/** Same providers as the SSR helper, on a live DOM so the picker can be clicked. */
function render(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: Infinity } } });
  return rtlRender(
    <QueryClientProvider client={client}>
      <AiChatProvider>{ui}</AiChatProvider>
    </QueryClientProvider>,
  );
}

const stock = { symbol: "HPG", instrumentType: "STOCK" } as never;
const warrant = {
  symbol: "CHPG2618", instrumentType: "CW", underlyingSymbol: "HPG", issuer: "KIS",
  strikePrice: 28888, exerciseRatio: 4, maturityDate: "2026-12-28", lastTradingDate: "2026-12-24",
} as never;

beforeEach(() => {
  requests.calls = [];
  const store: Record<string, string> = {};
  vi.stubGlobal("localStorage", {
    getItem: (k: string) => store[k] ?? null,
    setItem: (k: string, v: string) => { store[k] = String(v); },
    removeItem: (k: string) => { delete store[k]; },
    clear: () => { for (const k of Object.keys(store)) delete store[k]; },
  });
  // Effects run on a live DOM; no request may leave the test.
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response("{}", { status: 200 }))));
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const last = () => requests.calls[requests.calls.length - 1];
const chart = (page: ReturnType<typeof render>) => page.getByTestId("chart");

describe("instrument chart intervals", () => {
  it("offers intraday and day intervals and opens on daily candles from the deep series", () => {
    const page = render(<InstrumentPanel instrument={stock} marketSessionActive={false} onClose={vi.fn()} />);
    expect(page.getByRole("group", { name: "INTRADAY" }).textContent).toBe("INTRADAY1m5m30m1h");
    expect(page.getByRole("group", { name: "DAYS" }).textContent).toBe("DAYS1D5D1W3W1M3M6M1Y");
    expect(chart(page).dataset.interval).toBe("1D");
    expect(chart(page).dataset.bars).toBe(String(DAILY.length));
    expect(last()).toMatchObject({ timeframe: "MAX", interval: "1D", adjusted: true });
  });

  it("builds weekly candles from the same series without a new request", () => {
    const page = render(<InstrumentPanel instrument={stock} marketSessionActive={false} onClose={vi.fn()} />);
    const before = JSON.stringify(last());
    act(() => { fireEvent.click(page.getByRole("button", { name: "1W" })); });
    expect(chart(page).dataset.interval).toBe("1W");
    expect(Number(chart(page).dataset.bars)).toBe(24); // 120 sessions, Monday start = 24 weeks
    expect(JSON.stringify(last())).toBe(before);
  });

  it("asks the source for intraday bars at the chosen granularity, on the RAW key", () => {
    const page = render(<InstrumentPanel instrument={stock} marketSessionActive={false} onClose={vi.fn()} />);
    act(() => { fireEvent.click(page.getByRole("button", { name: "5m" })); });
    expect(last()).toMatchObject({ timeframe: "1M", interval: "5m", adjusted: false });
    expect(chart(page).dataset.interval).toBe("5m");
  });

  it("keeps warrants on RAW and says where their intraday history ends", () => {
    const page = render(<InstrumentPanel instrument={warrant} marketSessionActive={false} onClose={vi.fn()} />);
    expect(last()).toMatchObject({ timeframe: "MAX", interval: "1D", adjusted: false });
    expect(page.queryByText(/current session only/)).toBeNull();
    act(() => { fireEvent.click(page.getByRole("button", { name: "1h" })); });
    expect(page.getByText(/current session only/)).toBeTruthy();
  });

  it("keeps the current week's candle on the live print", () => {
    const today = DAILY[DAILY.length - 1];
    const quoted = {
      symbol: "HPG", instrumentType: "STOCK",
      quote: {
        symbol: "HPG", lastPrice: 7777, openPrice: today.open, highPrice: 7777, lowPrice: today.low,
        totalVolume: 900, marketSessionDate: today.date, tradeTimestamp: null,
        exchangeTimestamp: null, sourceTimestamp: null, receivedTimestamp: 0,
      },
    } as never;
    const page = render(<InstrumentPanel instrument={quoted} marketSessionActive={true} onClose={vi.fn()} />);
    act(() => { fireEvent.click(page.getByRole("button", { name: "1W" })); });
    expect(chart(page).dataset.lastClose).toBe("7777");
  });
});
