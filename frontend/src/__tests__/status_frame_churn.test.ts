// @vitest-environment happy-dom
/**
 * A status frame that changes nothing must not cost a render.
 *
 * During a busy session (2026-10-12) a status frame arrived 40-70 times a second, each
 * differing from the last only in its clocks. Each one re-announced the session, rebuilt
 * the 370-symbol universe set and scheduled a market revision - a render of every market
 * consumer. Half of the main thread went to that, in stalls that swallowed the 300 ms
 * value flashes.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BackendWebSocketClient } from "@/data/backend/backend_websocket_client";

let second = 0;
const status = (over: Record<string, unknown> = {}) => {
  second += 1;
  return {
    type: "status",
    sessionContext: {
      serverTime: new Date(Date.parse("2026-10-12T10:00:00+07:00") + second * 1_000).toISOString(),
      displaySessionDate: "2026-10-12",
      latestCompletedSession: "2026-10-09",
      marketPhase: "MORNING_SESSION",
      marketSessionActive: true,
      nextRolloverAt: null,
      calendarConfidence: "HIGH",
    },
    market_session: "MORNING_SESSION",
    market_phase: "MORNING_SESSION",
    market_session_active: true,
    upstream_status: "LIVE",
    connected: true,
    feed_fresh: true,
    ...over,
  };
};

function connectedClient() {
  const client = new BackendWebSocketClient("ws://example.test/ws/market");
  client.syncSubscriptions(["HPG", "VNM"]);
  const renders = vi.fn();
  client.subscribe(renders);
  const sessions = vi.fn();
  client.onMarketSessionChange(sessions);
  sessions.mockClear();
  client.handleIncomingMessage(status({ realtime_universe_symbols: ["HPG"] }));
  vi.advanceTimersByTime(100);
  return { client, renders, sessions };
}

describe("status frames", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("that only move the clock do not render or re-announce the session", () => {
    const { client, renders, sessions } = connectedClient();
    const settled = renders.mock.calls.length;
    expect(settled).toBeGreaterThan(0);
    expect(sessions).toHaveBeenCalledTimes(1);

    for (let i = 0; i < 60; i++) {
      client.handleIncomingMessage(status());
      vi.advanceTimersByTime(16);
    }
    // Repeating the same universe is not a change either.
    client.handleIncomingMessage(status({ realtime_universe_symbols: ["HPG"] }));
    vi.advanceTimersByTime(100);

    expect(renders).toHaveBeenCalledTimes(settled);
    expect(sessions).toHaveBeenCalledTimes(1);
    expect(client.isRealtimeTracked("HPG")).toBe(true);
    expect(client.isRealtimeTracked("VNM")).toBe(false);
  });

  it("that change the session render and announce it at once", () => {
    const { client, renders, sessions } = connectedClient();
    const settled = renders.mock.calls.length;

    client.handleIncomingMessage(status({
      market_session: "LUNCH_BREAK", market_phase: "LUNCH_BREAK", market_session_active: false,
    }));
    vi.advanceTimersByTime(100);

    expect(renders.mock.calls.length).toBeGreaterThan(settled);
    expect(sessions).toHaveBeenLastCalledWith({ status: "LUNCH_BREAK", active: false });
    expect(client.getMarketPhase()).toBe("LUNCH_BREAK");
  });

  it("that change the universe render and re-classify the watchlist", () => {
    const { client, renders } = connectedClient();
    const settled = renders.mock.calls.length;

    client.handleIncomingMessage(status({ realtime_universe_symbols: ["HPG", "VNM"] }));
    vi.advanceTimersByTime(100);

    expect(renders.mock.calls.length).toBeGreaterThan(settled);
    expect(client.isRealtimeTracked("VNM")).toBe(true);
  });
});
