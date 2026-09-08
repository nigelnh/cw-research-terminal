// @vitest-environment happy-dom
/**
 * The single server-authoritative answer to "what session is it".
 *
 * Components used to decide this independently — some from the browser clock, some from a
 * cache age, some from the 09:00 open rather than the 08:00 rollover — and disagreed with
 * each other for an hour every morning. This store exists so there is one answer, supplied
 * by the server, and it had no tests.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/data/query/query_client", () => ({
  appQueryClient: { invalidateQueries: vi.fn() },
}));

import { appQueryClient } from "@/data/query/query_client";

// The store is a module-level singleton and deliberately refuses updates that move
// backwards in time, so tests must each get a fresh module rather than share one.
type Store = typeof import("@/data/market_session_store");
let acceptMarketContext: Store["acceptMarketContext"];
let marketNow: Store["marketNow"];
let marketSessionStore: Store["marketSessionStore"];

const ctx = (over: Record<string, unknown> = {}) => ({
  serverTime: "2026-09-08T09:04:00+07:00",
  displaySessionDate: "2026-09-08",
  latestCompletedSession: "2026-09-07",
  marketPhase: "ATO",
  marketSessionActive: true,
  nextRolloverAt: null,
  calendarConfidence: "HIGH",
  ...over,
}) as never;

beforeEach(async () => {
  vi.clearAllMocks();
  vi.resetModules();
  ({ acceptMarketContext, marketNow, marketSessionStore } =
    await import("@/data/market_session_store"));
  // A prior session, so the first real update is a genuine rollover.
  acceptMarketContext({ sessionContext: ctx({
    serverTime: "2026-09-07T15:00:00+07:00", displaySessionDate: "2026-09-07",
    latestCompletedSession: "2026-09-04",
  }) });
  vi.clearAllMocks();
});

describe("marketSessionStore", () => {
  it("takes the server's session, not the browser's date", () => {
    acceptMarketContext({ sessionContext: ctx() });
    expect(marketSessionStore.getSnapshot().sessionContext?.displaySessionDate).toBe("2026-09-08");
  });

  it("ignores an update that moves the session backwards", () => {
    // A late response from before a rollover must not un-roll the board.
    acceptMarketContext({ sessionContext: ctx() });
    acceptMarketContext({ sessionContext: ctx({
      displaySessionDate: "2026-09-07", serverTime: "2026-09-07T15:00:00+07:00" }) });
    expect(marketSessionStore.getSnapshot().sessionContext?.displaySessionDate).toBe("2026-09-08");
  });

  it("ignores an update whose server time is older, even on the same session", () => {
    acceptMarketContext({ sessionContext: ctx() });
    acceptMarketContext({ sessionContext: ctx({
      serverTime: "2026-09-08T09:00:00+07:00", marketPhase: "PRE_OPEN" }) });
    expect(marketSessionStore.getSnapshot().sessionContext?.marketPhase).toBe("ATO");
  });

  it("ignores a payload with an unparseable server time", () => {
    acceptMarketContext({ sessionContext: ctx() });
    acceptMarketContext({ sessionContext: ctx({ serverTime: "not a time", marketPhase: "CLOSED" }) });
    expect(marketSessionStore.getSnapshot().sessionContext?.marketPhase).toBe("ATO");
  });

  it("drops every cached query when the session actually rolls", () => {
    acceptMarketContext({ sessionContext: ctx() });
    expect(appQueryClient.invalidateQueries).toHaveBeenCalled();
  });

  it("does not drop caches for an ordinary same-session update", () => {
    acceptMarketContext({ sessionContext: ctx() });
    vi.clearAllMocks();
    acceptMarketContext({ sessionContext: ctx({
      serverTime: "2026-09-08T09:05:00+07:00", marketPhase: "MORNING_SESSION" }) });
    expect(appQueryClient.invalidateQueries).not.toHaveBeenCalled();
  });

  it("keeps the previous feed status when an update omits it", () => {
    acceptMarketContext({ sessionContext: ctx(), feedStatus: {
      code: "ENTITLEMENT_EXPIRED", scope: "market_data", message: "expired" } });
    acceptMarketContext({ sessionContext: ctx({ serverTime: "2026-09-08T09:06:00+07:00" }) });
    expect(marketSessionStore.getSnapshot().feedStatus?.code).toBe("ENTITLEMENT_EXPIRED");
  });

  it("reads the clock from the server's time, not the machine's", () => {
    acceptMarketContext({ sessionContext: ctx() });
    // A browser hours out of sync must still report the server's session time.
    const drift = Math.abs(marketNow() - Date.parse("2026-09-08T09:04:00+07:00"));
    expect(drift).toBeLessThan(5_000);
  });

  it("notifies subscribers so panels re-read", () => {
    const seen = vi.fn();
    const off = marketSessionStore.subscribe(seen);
    acceptMarketContext({ sessionContext: ctx() });
    expect(seen).toHaveBeenCalled();
    off();
    acceptMarketContext({ sessionContext: ctx({ serverTime: "2026-09-08T09:07:00+07:00" }) });
    expect(seen).toHaveBeenCalledTimes(1);
  });
});
