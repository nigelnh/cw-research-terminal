// @vitest-environment happy-dom
import { beforeEach, afterEach, describe, it, expect, vi } from "vitest";
import {
  render,
  cleanup,
  fireEvent,
  within,
  waitFor,
} from "@testing-library/react";
import { useState, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { PersonalDashboard } from "@/features/watchlist/personal_dashboard";
import { NewsFeed } from "@/features/news_feed/news_feed";
import { AppHeader } from "@/components/common/app_header";
import { SignInDialog } from "@/features/auth/sign_in_dialog";
import { resetWatchlistMemoryForTests } from "@/data/watchlist/use_watchlist";
import { createDefaultWatchlist } from "@/domain/models/watchlist";
import { useResearchFeed } from "@/data/query/use_research_feed";

vi.mock("@/data/use_research_market", () => ({
  useResearchMarket: () => ({
    quotes: new Map(),
    warrants: new Map(),
    marketSessionActive: false,
  }),
}));
vi.mock("@/data/query/use_dashboard_data", () => ({
  useDashboardData: () => ({
    getRow: () => undefined,
    meta: { latestCompletedSession: null },
    isLoading: false,
    isError: false,
  }),
}));
vi.mock("@/data/instruments/use_instrument_specs", () => ({
  useInstrumentSpecs: () => ({
    getSpec: (symbol: string) =>
      symbol.startsWith("C")
        ? {
            underlyingSymbol: symbol === "CHPG2602" ? "HPG" : "VPB",
            issuer: "SSI",
            maturityDate: "2027-01-01",
          }
        : null,
  }),
}));
vi.mock("@/data/query/use_research_feed", () => ({
  useResearchFeed: vi.fn(() => ({
    items: [
      {
        id: "news_1",
        symbol: "HPG",
        title: "HPG: cổ tức",
        title_en: "Cash dividend",
        title_en_exact: false,
        published_at: "2026-09-01",
        display_date: "2026-09-01",
        date_kind: "published",
        source: "HOSE",
        content_type: "exchange_disclosure",
      },
    ],
    isLoading: false,
    isError: false,
    hasNextPage: false,
  })),
  useFeedFacets: () => ({ data: { symbols: ["HPG", "VPB", "VNM"] } }),
}));
vi.mock("@/data/auth", () => ({
  useAuth: () => ({
    user: null,
    status: "anonymous",
    isConfigured: true,
    signInWithEmail: async () => ({ ok: true, message: "Sent" }),
    signInWithGoogle: async () => {},
    signOut: async () => {},
  }),
  isGoogleAuthEnabled: () => false,
}));
function Wrapper({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: { queries: { retry: false, enabled: false } },
      }),
  );
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
beforeEach(() => {
  window.localStorage.clear();
  resetWatchlistMemoryForTests(createDefaultWatchlist());
  vi.clearAllMocks();
});
afterEach(cleanup);

describe("Shared workspace interactions", () => {
  it("keeps one schema for stock/CW, toggles Full, and activates rows with the keyboard", () => {
    const select = vi.fn();
    const v = render(<PersonalDashboard onSelectSymbol={select} />, {
      wrapper: Wrapper,
    });
    expect(v.getAllByRole("table")).toHaveLength(1);
    expect(v.queryByRole("button", { name: "STRIKE" })).toBeNull();
    fireEvent.click(v.getByRole("button", { name: "Full" }));
    expect(v.getByRole("button", { name: "STRIKE" })).toBeTruthy();
    fireEvent.keyDown(v.getByText("HPG").closest("tr")!, { key: "Enter" });
    expect(select).toHaveBeenCalledWith("HPG");
  });
  it("preserves parent/child grouping while sorting and pinning", () => {
    const v = render(<PersonalDashboard />, { wrapper: Wrapper });
    fireEvent.click(v.getByRole("button", { name: "SYMBOL" }));
    expect(
      v.getByRole("columnheader", { name: "SYMBOL" }).getAttribute("aria-sort"),
    ).toBe("ascending");
    fireEvent.click(v.getByRole("button", { name: "Pin VPB" }));
    const rows = within(v.getByRole("table")).getAllByRole("row").slice(1);
    expect(rows[0].textContent).toContain("VPB");
    expect(rows[1].textContent).toContain("CVPB2615");
    fireEvent.click(v.getByRole("button", { name: "Pin CHPG2602" }));
    const pinned = within(v.getByRole("table")).getAllByRole("row").slice(1);
    expect(pinned[0].textContent).toContain("VPB"); // CW pin cannot escape its parent group
  });
  it("Hide preserves membership and both Hide and Remove have Undo", () => {
    const v = render(<PersonalDashboard />, { wrapper: Wrapper });
    fireEvent.click(v.getByRole("button", { name: "Actions for CHPG2602" }));
    fireEvent.click(v.getByRole("button", { name: "Hide from view" }));
    expect(
      v.queryByRole("button", { name: "Actions for CHPG2602" }),
    ).toBeNull();
    expect(v.getByText("1 hidden from this view")).toBeTruthy();
    fireEvent.click(v.getByRole("button", { name: "Undo" }));
    fireEvent.click(v.getByRole("button", { name: "Actions for CHPG2602" }));
    fireEvent.click(v.getByRole("button", { name: "Remove from watchlist" }));
    expect(
      v.queryByRole("button", { name: "Actions for CHPG2602" }),
    ).toBeNull();
    fireEvent.click(v.getByRole("button", { name: "Undo" }));
    expect(
      v.getByRole("button", { name: "Actions for CHPG2602" }),
    ).toBeTruthy();
  });
  it("filter stays open during date editing, closes on Escape and restores focus", () => {
    const v = render(<PersonalDashboard />, { wrapper: Wrapper });
    const trigger = v.getByRole("button", { name: "Filters" });
    fireEvent.click(trigger);
    const dialog = v.getByRole("dialog", { name: "Filters" });
    const input = dialog.querySelector('input[type="date"]')!;
    fireEvent.change(input, { target: { value: "2026-09-01" } });
    expect(v.getByRole("dialog", { name: "Filters" })).toBeTruthy();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(v.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(trigger);
    fireEvent.click(trigger);
    fireEvent.pointerDown(document.body);
    expect(v.queryByRole("dialog")).toBeNull();
  });
  it("header slash/search/Enter jumps to a symbol, Escape closes suggestions", () => {
    const select = vi.fn();
    const v = render(
      <AppHeader
        activeTab="dashboard"
        onTabChange={vi.fn()}
        marketSessionActive={false}
        symbols={["HPG", "VPB"]}
        onSelectSymbol={select}
      />,
    );
    fireEvent.keyDown(document.body, { key: "/" });
    const input = v.getByRole("combobox");
    expect(document.activeElement).toBe(input);
    fireEvent.change(input, { target: { value: "HPG" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(select).toHaveBeenCalledWith("HPG");
    fireEvent.change(input, { target: { value: "VPB" } });
    fireEvent.keyDown(input, { key: "Escape" });
    expect(v.queryByRole("listbox")).toBeNull();
  });
});

describe("News scope and auth", () => {
  it("dividend is a text query; ticker clicks open detail without changing scope", () => {
    const select = vi.fn();
    const v = render(<NewsFeed onSelectSymbol={select} />, {
      wrapper: Wrapper,
    });
    fireEvent.change(v.getByRole("textbox", { name: "Search news" }), {
      target: { value: "dividend" },
    });
    expect(vi.mocked(useResearchFeed).mock.lastCall?.[0]).toMatchObject({
      query: "dividend",
      symbols: null,
    });
    fireEvent.click(v.getByRole("button", { name: "HPG" }));
    expect(select).toHaveBeenCalledWith("HPG");
    expect(
      v
        .getByRole("button", { name: "All market" })
        .getAttribute("aria-pressed"),
    ).toBe("true");
    expect(v.queryByText("Original (Vietnamese)")).toBeNull();
    fireEvent.click(v.getByRole("button", { name: "Watchlist" }));
    expect(vi.mocked(useResearchFeed).mock.lastCall?.[0]?.symbols).toEqual(
      expect.arrayContaining(["HPG", "VPB", "CHPG2602"]),
    );
  });
  it("sign-in labels/focus/close and email feedback work without real email", async () => {
    function AuthTest() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button onClick={() => setOpen(true)}>Launch</button>
          {open && <SignInDialog onClose={() => setOpen(false)} />}
        </>
      );
    }
    const v = render(<AuthTest />);
    const launch = v.getByRole("button", { name: "Launch" });
    launch.focus();
    fireEvent.click(launch);
    const email = v.getByLabelText("Email");
    expect(document.activeElement).toBe(email);
    fireEvent.change(email, { target: { value: "review@example.com" } });
    fireEvent.submit(email.closest("form")!);
    await waitFor(() =>
      expect(v.getByRole("status").textContent).toContain(
        "Check review@example.com",
      ),
    );
    fireEvent.click(v.getByRole("button", { name: "Close sign in" }));
    expect(v.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(launch);
  });
});
