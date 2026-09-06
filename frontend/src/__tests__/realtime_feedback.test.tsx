// @vitest-environment happy-dom
import { act, cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RealtimeValue, REALTIME_FLASH_DURATION_MS, RollingNumber } from "@/components/common/realtime_value";
import { __setReducedMotionForTests } from "@/design/motion";
import { quoteCell } from "@/components/common/quote_columns";
import { MARKET_COLOR, priceColor } from "@/components/common/grid_table";
import { BackendWebSocketClient } from "@/data/backend/backend_websocket_client";
import { applyRawPatchToQuote } from "@/data/backend/mappers/map_patch";
import { mapRawSnapshotToQuote } from "@/data/backend/mappers/map_snapshot";

const snapshot = (overrides: Record<string, unknown> = {}) => ({
  Symbol: "HPG",
  InstrumentType: "STOCK",
  Traded: 22.1,
  Ref: 22.2,
  Ceil: 23.75,
  Floor: 20.65,
  Total_Vol: 1_000,
  Change: -0.1,
  ChangePercent: -0.45,
  _ts_source: 1_780_000_000_000,
  ...overrides,
});

describe("incremental realtime feedback", () => {
  it("flashes the table cell itself for the wake duration and cleans up after expiry", () => {
    vi.useFakeTimers();
    try {
      const { container, unmount } = render(<table><tbody><tr>
        <RealtimeValue as="td" title="Traded price" style={{ padding: "8px" }}
          pulse={{ sequence: 1, direction: "up", startedAt: Date.now() }}>21,700</RealtimeValue>
      </tr></tbody></table>);
      expect(container.querySelector("td.realtime-flash-up")?.textContent).toBe("21,700");
      expect(container.querySelector("td span")).toBeNull();
      act(() => vi.advanceTimersByTime(REALTIME_FLASH_DURATION_MS - 20));
      expect(container.querySelector("td.realtime-flash-up")).not.toBeNull();
      act(() => vi.advanceTimersByTime(21));
      expect(container.querySelector(".realtime-flash")).toBeNull();
      expect(REALTIME_FLASH_DURATION_MS).toBe(620);
      unmount();
    } finally { vi.useRealTimers(); }
  });
  it("uses the same five-state price classifier for stock and CW rows", () => {
    const bands = { ref: 100, ceiling: 107, floor: 93 };
    const states = [
      [107, MARKET_COLOR.ceiling],
      [101, MARKET_COLOR.up],
      [100, MARKET_COLOR.flat],
      [99, MARKET_COLOR.down],
      [93, MARKET_COLOR.floor],
    ] as const;
    for (const [price, color] of states) {
      expect(priceColor(price, bands)).toBe(color);
    }
    expect(priceColor(101, { ref: null, ceiling: null, floor: null })).toBe(
      MARKET_COLOR.null,
    );
  });

  it("accepts the canonical lowercase change wire key and records direction", () => {
    const before = mapRawSnapshotToQuote(snapshot());
    const after = applyRawPatchToQuote(before, "HPG", {
      Traded: 22.3,
      change: 0.1,
      ChangePercent: 0.45,
    });

    expect(after.priceChange).toBe(100);
    expect(after.realtimePulses?.lastPrice?.direction).toBe("up");
    expect(after.realtimePulses?.priceChange?.direction).toBe("up");
    expect(after.realtimePulses?.priceChangePercent?.direction).toBe("up");
  });

  it("renders a change-only patch without waiting for another trade-price patch", () => {
    const before = mapRawSnapshotToQuote(snapshot());
    const after = applyRawPatchToQuote(before, "HPG", { change: 0.2 });
    const rendered = quoteCell(
      {
        symbol: "HPG",
        ref: after.referencePrice,
        ceiling: after.ceilingPrice,
        floor: after.floorPrice,
        bid: null,
        ask: null,
        last: after.lastPrice,
        tradedQuantity: null,
        change: after.priceChange,
        chgPct: null,
        vol: null,
        strike: null,
        ratio: null,
        ivBid: null,
        ivTrade: null,
        ivAsk: null,
        lastTradingDate: null,
        dteText: "—",
      },
      "change",
    );

    expect(after.lastPrice).toBe(22_100);
    expect(rendered.text).toBe("+200");
  });

  it("does not pulse a full snapshot and retriggers consecutive same-direction patches", () => {
    const client = new BackendWebSocketClient("ws://example.test/ws/market");
    client.handleIncomingMessage({
      type: "status",
      market_session: "MORNING_SESSION",
      market_session_date: "2026-09-02",
      market_session_active: true,
      upstream_status: "LIVE",
      feed_fresh: true,
    });
    client.handleIncomingMessage({ type: "snapshots", rows: [snapshot()] });
    expect(client.getQuote("HPG")?.realtimePulses).toBeUndefined();

    client.handleIncomingMessage({ type: "patch", symbol: "HPG", patch: { Traded: 22.2 } });
    expect(client.getQuote("HPG")?.realtimePulses?.lastPrice).toMatchObject({
      sequence: 1,
      direction: "up",
    });
    client.handleIncomingMessage({ type: "patch", symbol: "HPG", patch: { Traded: 22.3 } });
    expect(client.getQuote("HPG")?.realtimePulses?.lastPrice).toMatchObject({
      sequence: 2,
      direction: "up",
    });
  });

  it("rejects an out-of-order stock patch using the stock quote timestamp", () => {
    const client = new BackendWebSocketClient("ws://example.test/ws/market");
    client.handleIncomingMessage({
      type: "snapshot",
      row: snapshot({ _ts_source: 2_000 }),
    });

    client.handleIncomingMessage({
      type: "patch",
      symbol: "HPG",
      patch: { Traded: 23, _ts_source: 1_999 },
    });

    expect(client.getQuote("HPG")?.lastPrice).toBe(22_100);
  });

  it("establishes a fresh baseline after the ICT session changes", () => {
    const client = new BackendWebSocketClient("ws://example.test/ws/market");
    client.handleIncomingMessage({
      type: "status",
      market_session: "CLOSED_POST_MARKET",
      market_session_date: "2026-09-02",
      market_session_active: false,
    });
    client.handleIncomingMessage({ type: "snapshots", rows: [snapshot()] });
    client.handleIncomingMessage({ type: "patch", symbol: "HPG", patch: { Traded: 22.2 } });
    expect(client.getQuote("HPG")?.realtimePulses?.lastPrice).toBeDefined();

    client.handleIncomingMessage({
      type: "status",
      market_session: "MORNING_SESSION",
      market_session_date: "2026-09-03",
      market_session_active: true,
      upstream_status: "LIVE",
      feed_fresh: true,
    });
    client.handleIncomingMessage({ type: "patch", symbol: "HPG", patch: { Traded: 22.3 } });
    expect(client.getQuote("HPG")?.realtimePulses).toBeUndefined();
  });

  it("uses the first dated patch as the rollover baseline before the next status heartbeat", () => {
    const client = new BackendWebSocketClient("ws://example.test/ws/market");
    client.handleIncomingMessage({
      type: "status",
      market_session_date: "2026-09-02",
      market_session_active: true,
      upstream_status: "LIVE",
      feed_fresh: true,
    });
    client.handleIncomingMessage({ type: "snapshots", rows: [snapshot()] });
    client.handleIncomingMessage({
      type: "patch",
      symbol: "HPG",
      patch: { Traded: 22.3, _market_session_date: "2026-09-03" },
    });
    expect(client.getQuote("HPG")?.realtimePulses).toBeUndefined();

    client.handleIncomingMessage({
      type: "patch",
      symbol: "HPG",
      patch: { Traded: 22.4, _market_session_date: "2026-09-03" },
    });
    expect(client.getQuote("HPG")?.realtimePulses?.lastPrice?.direction).toBe("up");
  });

  it("establishes one analytics baseline after a session rollover, then pulses", () => {
    const client = new BackendWebSocketClient("ws://example.test/ws/market");
    client.handleIncomingMessage({
      type: "status",
      market_session: "CLOSED_POST_MARKET",
      market_session_date: "2026-09-02",
      market_session_active: false,
    });
    client.handleIncomingMessage({
      type: "snapshot",
      row: { ...snapshot({ Symbol: "CHPG2617", InstrumentType: "CW" }), Vol2: 20 },
    });
    client.handleIncomingMessage({
      type: "status",
      market_session: "MORNING_SESSION",
      market_session_date: "2026-09-03",
      market_session_active: true,
      upstream_status: "LIVE",
      feed_fresh: true,
    });
    client.handleIncomingMessage({
      type: "analytics_patch",
      symbol: "CHPG2617",
      analytics: { iv_trade: 0.21 },
    });
    expect(client.getCoveredWarrant("CHPG2617")?.realtimePulses).toBeUndefined();

    client.handleIncomingMessage({
      type: "analytics_patch",
      symbol: "CHPG2617",
      analytics: { iv_trade: 0.22 },
    });
    expect(client.getCoveredWarrant("CHPG2617")?.realtimePulses?.ivTrade).toMatchObject({
      sequence: 1,
      direction: "up",
    });
  });

  it("uses the pulse sequence as a remount key for repeated CSS animation", () => {
    const page = render(
      <RealtimeValue pulse={{ sequence: 1, direction: "down" }}>22,100</RealtimeValue>,
    );
    expect(page.container.firstElementChild?.getAttribute("data-flash-sequence")).toBe("1");
    expect(page.container.firstElementChild?.classList.contains("realtime-flash-down")).toBe(true);

    page.rerender(
      <RealtimeValue pulse={{ sequence: 2, direction: "down" }}>22,000</RealtimeValue>,
    );
    expect(page.container.firstElementChild?.getAttribute("data-flash-sequence")).toBe("2");
  });

  it("does not replay an expired pulse when a value surface mounts later", () => {
    const page = render(
      <RealtimeValue pulse={{ sequence: 4, direction: "up", startedAt: Date.now() - REALTIME_FLASH_DURATION_MS - 1 }}>
        22,100
      </RealtimeValue>,
    );

    expect(page.container.firstElementChild?.classList.contains("realtime-flash-up")).toBe(false);
    expect(page.container.firstElementChild?.getAttribute("data-flash-sequence")).toBeNull();
  });

  it("marks requested symbols outside the fixed server universe as untracked", () => {
    const client = new BackendWebSocketClient("ws://example.test/ws/market");
    client.syncSubscriptions(["HPG", "VNM"]);
    client.handleIncomingMessage({
      type: "status",
      realtime_universe_symbols: ["HPG"],
      market_session: "MORNING_SESSION",
      market_session_active: true,
      upstream_status: "LIVE",
      feed_fresh: true,
    });
    expect(client.isRealtimeTracked("HPG")).toBe(true);
    expect(client.isRealtimeTracked("VNM")).toBe(false);
  });

  it("honors the server subscription acknowledgement for unavailable symbols", () => {
    const client = new BackendWebSocketClient("ws://example.test/ws/market");
    client.syncSubscriptions(["HPG", "VNM"]);
    client.handleIncomingMessage({
      type: "subscription_ack",
      accepted_symbols: ["HPG"],
      outside_symbols: ["VNM"],
    });

    expect(client.isRealtimeTracked("HPG")).toBe(true);
    expect(client.isRealtimeTracked("VNM")).toBe(false);
  });
});

describe("RollingNumber", () => {
  afterEach(() => {
    __setReducedMotionForTests(null);
    cleanup();
  });

  it("renders the display string and swaps it on value change", () => {
    const page = render(<RollingNumber value={1984.89} display="1,984.89" resetKey="2026-09-04" />);
    expect(page.getByText("1,984.89")).toBeTruthy();
    page.rerender(<RollingNumber value={1990.12} display="1,990.12" resetKey="2026-09-04" />);
    expect(page.getByText("1,990.12")).toBeTruthy();
  });

  it("under reduced motion, updates in place with no ghost element", () => {
    __setReducedMotionForTests(true);
    const page = render(<RollingNumber value={100} display="100" resetKey="s1" />);
    page.rerender(<RollingNumber value={102} display="102" resetKey="s1" />);
    expect(page.container.querySelector(".rolling-number-ghost")).toBeNull();
    expect(page.getByText("102")).toBeTruthy();
    // the directional wake still fires (it carries the up/down signal without motion)
    expect(page.container.querySelector(".realtime-flash-up")).not.toBeNull();
  });

  it("does not treat a session rollover (resetKey change) as a tick", () => {
    __setReducedMotionForTests(true);
    const page = render(<RollingNumber value={100} display="100" resetKey="mon" />);
    page.rerender(<RollingNumber value={2} display="2" resetKey="tue" />);
    expect(page.container.querySelector(".realtime-flash-up")).toBeNull();
    expect(page.container.querySelector(".realtime-flash-down")).toBeNull();
  });

  it("retargets on a mid-roll re-tick — ends on the newest value, one current node", () => {
    __setReducedMotionForTests(false);
    const page = render(<RollingNumber value={100} display="100" resetKey="s" />);
    // three ticks back to back
    page.rerender(<RollingNumber value={103} display="103" resetKey="s" />);
    page.rerender(<RollingNumber value={101} display="101" resetKey="s" />);
    page.rerender(<RollingNumber value={107} display="107" resetKey="s" />);
    // the visible current value is the last one; ghosts are aria-hidden and never stack
    expect(page.container.querySelector(".rolling-number-cur")?.textContent).toBe("107");
    expect(page.container.querySelectorAll(".rolling-number-cur")).toHaveLength(1);
  });
});
