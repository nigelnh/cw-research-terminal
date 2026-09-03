// @vitest-environment happy-dom
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { RealtimeValue } from "@/components/common/realtime_value";
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
        tradingValue: null,
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
      <RealtimeValue pulse={{ sequence: 4, direction: "up", startedAt: Date.now() - 601 }}>
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
