// @vitest-environment happy-dom
/**
 * The feed notice must not push the header's right-hand group over the clock.
 *
 * `.terminal-header` is a three-column grid whose end track is `minmax(0, 1fr)` with
 * `white-space: nowrap`. A child that cannot shrink overflows LEFTWARDS out of that track
 * and slides under the centred search box, which has a higher z-index and paints over it.
 * Measured on production after the notice landed: 155px of overlap, with the date reduced
 * to a bare "ICT".
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const feed = { current: null as Record<string, unknown> | null };
vi.mock("@/data/market_session_store", () => ({
  useMarketContext: () => ({ sessionContext: null, feedStatus: feed.current }),
  marketNow: () => Date.parse("2026-09-08T10:14:40+07:00"),
}));
vi.mock("@/data/auth", () => ({ useAuth: () => ({ user: null, signOut: vi.fn() }) }));
vi.mock("@/features/auth/sign_in_dialog", () => ({ SignInDialog: () => null }));

import { AppHeader } from "@/components/common/app_header";

afterEach(cleanup);   // one header per case, or every role="status" query is ambiguous

const EXPIRED = {
  code: "ENTITLEMENT_EXPIRED", scope: "market_data",
  message: "Market data access has expired. The data provider account needs renewal.",
  lastDataAt: "2026-09-07T14:45:00+07:00",
};

function header() {
  return render(
    <AppHeader
      activeTab="dashboard" onTabChange={vi.fn()}
      filter="" onFilterChange={vi.fn()}
      marketSessionActive={false} marketPhase="CONTINUOUS_AM"
    />,
  );
}

describe("header feed notice", () => {
  it("shows the reason the feed is down", () => {
    feed.current = EXPIRED;
    header();
    expect(screen.getByRole("status").textContent).toContain("expired");
  });

  it("can shrink, so it cannot shove the group across the clock", () => {
    feed.current = EXPIRED;
    header();
    const style = screen.getByRole("status").style;
    // Any one of these missing reproduces the 155px overlap.
    expect(parseFloat(style.minWidth)).toBe(0);
    expect(style.overflow).toBe("hidden");
    expect(style.textOverflow).toBe("ellipsis");
    expect(style.whiteSpace).toBe("nowrap");
  });

  it("keeps the full text and the last-data time reachable when truncated", () => {
    feed.current = EXPIRED;
    header();
    const title = screen.getByRole("status").getAttribute("title") ?? "";
    expect(title).toContain("needs renewal");
    expect(title).toContain("2026-09-07T14:45:00+07:00");
  });

  it("stays out of the way when the feed is healthy", () => {
    feed.current = { code: "AVAILABLE", scope: "market_data", message: "Market data is available." };
    header();
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("stays out of the way when the market is simply closed", () => {
    // A closed market is not a fault and must not read as one.
    feed.current = { code: "SESSION_PAUSED", scope: "market_data", message: "Matching is paused." };
    header();
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("renders nothing at all before any status has arrived", () => {
    feed.current = null;
    header();
    expect(screen.queryByRole("status")).toBeNull();
  });
});

/**
 * A layout guard, asserted against the stylesheet source.
 *
 * The first version of this file asserted the notice's own inline styles and passed while
 * the header was still visibly broken: the overlap was never about the notice's shrinking
 * rules, it was that `.terminal-header-end` used `justify-self: end`, which sizes a grid
 * item to its CONTENT instead of its track. The box grew to 781px inside a 560px column
 * and hung to the left, under the search box. Style-property assertions are not layout
 * assertions, and happy-dom has no layout engine to catch this - so this pins the rule
 * itself, and the geometry was verified in a real browser.
 */
describe("header end-group layout", () => {
  // Read from disk: vitest stubs CSS imports, so `?raw` yields an empty string here.
  const globalCss = readFileSync(resolve(process.cwd(), "src/design/global.css"), "utf8");
  const from = globalCss.indexOf(".terminal-header-end {");
  const rule = globalCss.slice(from, globalCss.indexOf("}", from) + 1);

  it("fills its grid track rather than sizing to its content", () => {
    expect(rule).toContain("justify-self: stretch");
    expect(rule).not.toContain("justify-self: end");
  });

  it("right-aligns inside the track, so nothing hangs into the search column", () => {
    expect(rule).toContain("justify-content: flex-end");
  });

  it("still clips rather than spilling", () => {
    expect(rule).toContain("overflow: hidden");
    expect(rule).toContain("min-width: 0");
  });
});
