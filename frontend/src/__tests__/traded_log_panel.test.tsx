// @vitest-environment happy-dom
/**
 * TRADED LOGS rendering. The tape is server-backed and kept until 08:00 ICT the morning
 * after its session, so the panel must stay populated after the close rather than going
 * blank at 15:00 as it used to.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, within } from "@testing-library/react";

const tape = vi.hoisted(() => ({
  items: [] as any[],
  sessionDate: null as string | null,
  isLoading: false,
  isError: false,
}));
vi.mock("@/data/query/use_traded_log", () => ({
  useTradedLog: () => ({ ...tape, sideBasis: "DERIVED_FROM_BOOK" }),
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

const cw = {
  symbol: "CHPG2627",
  instrumentType: "CW" as const,
  underlyingSymbol: "HPG",
  metadataVerification: "VERIFIED_CURRENT" as const,
};

function panel(live: boolean) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <InstrumentPanel instrument={cw as never} marketSessionActive={live} onClose={() => {}} />
    </QueryClientProvider>,
  );
}

const print = (o: Partial<Record<string, unknown>> = {}) => ({
  ts: 1_757_000_000_000, time: "09:20:31", price: 1_190,
  change: 80, change_percent: 0.0721, volume: 12_000, side: "B",
  session_date: "2026-09-07", ...o,
});

afterEach(() => {
  cleanup();
  tape.items = [];
  tape.sessionDate = null;
  tape.isLoading = false;
  tape.isError = false;
});

describe("TRADED LOGS", () => {
  it("renders a print with time, price, change, volume and the derived side", () => {
    tape.items = [print()];
    tape.sessionDate = "2026-09-07";
    const view = panel(true);
    const body = view.getByText("TRADED LOGS").closest("div")!.parentElement!;
    const text = body.textContent ?? "";
    expect(text).toContain("09:20:31");
    expect(text).toContain("1,190");
    expect(text).toContain("+80");
    expect(text).toContain("+7.21%");
    expect(text).toContain("12,000");
    expect(text).toContain("B");
    // The session date chip was removed from the heading: the tape's own rows carry the
    // time, and the panel already states which instrument and session it is showing.
    expect(text).not.toContain("2026-09-07");
  });

  it("keeps showing the tape after the close, not an 'unavailable' message", () => {
    tape.items = [print()];
    const text = panel(false).container.textContent ?? "";
    expect(text).toContain("09:20:31");
    expect(text).not.toContain("unavailable outside a live session");
  });

  it("leaves an unclassifiable print blank rather than guessing a side", () => {
    tape.items = [print({ side: null })];
    const view = panel(true);
    // the row renders, but no B and no S for it
    expect((view.container.textContent ?? "")).toContain("09:20:31");
    const cells = within(view.container).queryAllByText(/^[BS]$/);
    expect(cells).toHaveLength(0);
  });

  it("distinguishes an empty live session from an empty last session", () => {
    expect(panel(true).container.textContent).toContain("No matches yet this session.");
    cleanup();
    expect(panel(false).container.textContent).toContain("No matches recorded for the last session.");
  });

  it("says so plainly when the tape could not be read", () => {
    tape.isError = true;
    expect(panel(true).container.textContent).toContain("Traded logs unavailable.");
  });

  it("labels the B/S column as derived, since the exchange does not publish it", () => {
    tape.items = [print()];
    const header = panel(true).getByTitle(/derived from the order book/i);
    expect(header.textContent).toBe("B/S");
  });
});
