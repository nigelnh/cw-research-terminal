import { describe, it, expect } from "vitest";
import { BackendWebSocketClient } from "../data/backend/backend_websocket_client";
import { BackendMarketDataProvider } from "../data/backend/backend_market_data_provider";
import { renderToStaticMarkup } from "react-dom/server";
import { createElement } from "react";
import { AppHeader } from "../components/common/app_header";

describe("Live Status Semantics & Two-State Tracking", () => {
  it("1. Tracks gateway and upstream feed states independently", () => {
    const client = new BackendWebSocketClient("ws://localhost:8787");

    expect(client.getGatewayState()).toBe("DISCONNECTED");
    expect(client.getUpstreamFeedState()).toBe("UNKNOWN");
  });

  it("2. Transitions upstream feed to DISCONNECTED when receiving status connected=false", () => {
    const client = new BackendWebSocketClient("ws://localhost:8787");
    const feedStates: string[] = [];

    client.onUpstreamFeedStateChange((state) => feedStates.push(state));

    // Gateway connected, but upstream feed is disconnected
    client.handleIncomingMessage({
      type: "status",
      connected: false,
      message: "Disconnected from upstream feed",
    });

    expect(client.getUpstreamFeedState()).toBe("DISCONNECTED");
    expect(feedStates).toContain("DISCONNECTED");
  });

  it("3. Transitions upstream feed to CONNECTED when receiving status connected=true", () => {
    const client = new BackendWebSocketClient("ws://localhost:8787");
    const feedStates: string[] = [];

    client.onUpstreamFeedStateChange((state) => feedStates.push(state));

    client.handleIncomingMessage({
      type: "status",
      connected: true,
      message: "Connected to upstream feed",
    });

    expect(client.getUpstreamFeedState()).toBe("CONNECTED");
    expect(feedStates).toContain("CONNECTED");
  });

  it("4. Does not infer a live upstream feed from a cached snapshot", () => {
    const client = new BackendWebSocketClient("ws://localhost:8787");
    expect(client.getUpstreamFeedState()).toBe("UNKNOWN");

    client.handleIncomingMessage({
      type: "snapshots",
      rows: [{ Symbol: "CHPG2401", Traded: 1.35, Strike_Prc: 28.0, Ratio: 2.0 }],
      ts: Date.now(),
    });

    expect(client.getUpstreamFeedState()).toBe("UNKNOWN");
  });

  it("5. Resets upstream feed state to UNKNOWN when gateway disconnects", () => {
    const client = new BackendWebSocketClient("ws://localhost:8787");

    client.handleIncomingMessage({
      type: "status",
      connected: true,
    });
    expect(client.getUpstreamFeedState()).toBe("CONNECTED");

    // Gateway disconnects
    client.disconnect();
    expect(client.getGatewayState()).toBe("DISCONNECTED");
    expect(client.getUpstreamFeedState()).toBe("UNKNOWN");
  });

  it("6. BackendMarketDataProvider propagates live gateway states directly to consumers", () => {
    const wsClient = new BackendWebSocketClient("ws://localhost:8787");
    const provider = new BackendMarketDataProvider(wsClient);
    expect(provider.getConnectionState()).toBe("DISCONNECTED");
    expect(provider.getUpstreamFeedState()).toBe("UNKNOWN");

    wsClient.handleIncomingMessage({
      type: "status",
      connected: true,
    });
    expect(provider.getUpstreamFeedState()).toBe("CONNECTED");
  });

  it("7. Handles LUNCH_BREAK session without dropping to false disconnected", () => {
    const client = new BackendWebSocketClient("ws://localhost:8787");

    client.handleIncomingMessage({
      type: "status",
      gateway_connected: true,
      authenticated: true,
      upstream_status: "READY",
      connected: false,
      market_session: "LUNCH_BREAK",
      market_session_active: false,
      quote_display_eligible: false,
    });

    expect(client.getMarketSession()).toBe("LUNCH_BREAK");
    expect(client.isMarketSessionActive()).toBe(false);
    expect(client.getUpstreamFeedState()).toBe("CONNECTED");
  });

  it("8. Preserves explicit reconnecting state while the feed is not fresh", () => {
    const client = new BackendWebSocketClient("ws://localhost:8787");

    client.handleIncomingMessage({
      type: "status",
      upstream_status: "RECONNECTING",
      feed_fresh: false,
      market_session: "MORNING_SESSION",
      market_session_active: true,
    });

    expect(client.getUpstreamFeedState()).toBe("RECONNECTING");
  });

  it("9. Treats a ready upstream as connected outside the active session", () => {
    const client = new BackendWebSocketClient("ws://localhost:8787");

    client.handleIncomingMessage({
      type: "status",
      gateway_connected: true,
      authenticated: true,
      upstream_status: "READY",
      feed_fresh: false,
      market_session: "CLOSED_POST_MARKET",
      market_session_active: false,
      quote_display_eligible: false,
    });

    expect(client.getMarketSession()).toBe("CLOSED_POST_MARKET");
    expect(client.isMarketSessionActive()).toBe(false);
    expect(client.getUpstreamFeedState()).toBe("CONNECTED");
  });

  it("10. Does not infer a live feed from a legacy index snapshot", () => {
    const client = new BackendWebSocketClient("ws://localhost:8787");

    client.handleIncomingMessage({
      type: "index_update",
      data: { symbol: "VNINDEX", value: 1832.12 },
    });

    expect(client.getUpstreamFeedState()).toBe("UNKNOWN");
  });

  it("11. Does not let a data patch override backend feed health", () => {
    const client = new BackendWebSocketClient("ws://localhost:8787");
    client.handleIncomingMessage({
      type: "status",
      upstream_status: "RECONNECTING",
      feed_fresh: false,
      market_session_active: true,
    });

    client.handleIncomingMessage({
      type: "patch",
      symbol: "HPG",
      patch: { Traded: 22.1, _market_session_date: "2026-09-03" },
    });

    expect(client.getUpstreamFeedState()).toBe("RECONNECTING");
  });

  it("12. Renders market-session and feed state independently", () => {
    const html = renderToStaticMarkup(createElement(AppHeader, {
      activeTab: "dashboard",
      onTabChange: () => undefined,
      filter: "",
      onFilterChange: () => undefined,
      marketSessionActive: false,
      gatewayState: "RECONNECTING",
      upstreamFeedState: "RECONNECTING",
    }));

    expect(html).toContain("CLOSED");
    expect(html).toContain("RECONNECTING");
  });

  it("hides the idle READY badge while retaining the closed-session label", () => {
    const html = renderToStaticMarkup(createElement(AppHeader, {
      activeTab: "dashboard", onTabChange: () => undefined,
      filter: "", onFilterChange: () => undefined,
      marketSessionActive: false, gatewayState: "CONNECTED", upstreamFeedState: "CONNECTED",
    }));
    expect(html).toContain("CLOSED");
    expect(html).not.toContain("READY");
    expect(html).not.toContain("Market feed");
  });

  it.each([
    ["PRE_OPEN", false, "PRE-OPEN"], ["ATO", true, "ATO"],
    ["CONTINUOUS_AM", true, "OPEN"], ["LUNCH_BREAK", false, "LUNCH BREAK"],
    ["CONTINUOUS_PM", true, "OPEN"], ["ATC", true, "ATC"],
    ["POST_CLOSE_NEGOTIATED", true, "NEGOTIATED"], ["CLOSED", false, "CLOSED"],
    ["UNKNOWN", false, "SYNCING"],
  ] as const)("renders phase %s separately from connection health", (phase, active, label) => {
    const html = renderToStaticMarkup(createElement(AppHeader, {
      activeTab: "dashboard", onTabChange: () => undefined,
      filter: "", onFilterChange: () => undefined,
      marketPhase: phase, marketSessionActive: active,
      gatewayState: "CONNECTED", upstreamFeedState: "CONNECTED",
    }));
    expect(html).toContain(`Market session ${label.toLowerCase()}`);
    expect(html).not.toContain("READY");
  });

  const header = (
    active: boolean,
    gateway: Parameters<typeof AppHeader>[0]["gatewayState"],
    upstream: Parameters<typeof AppHeader>[0]["upstreamFeedState"],
  ) =>
    renderToStaticMarkup(createElement(AppHeader, {
      activeTab: "dashboard", onTabChange: () => undefined,
      filter: "", onFilterChange: () => undefined,
      marketSessionActive: active, gatewayState: gateway, upstreamFeedState: upstream,
    }));

  // The feed chip is exception-only. A healthy feed shows nothing at all: the session chip
  // beside it already reads OPEN with a green dot, so a second "LIVE" badge was duplication.
  it.each([
    [false, "CONNECTED", "STALE", "STALE"],
    [false, "DISCONNECTED", "DISCONNECTED", "OFFLINE"],
    [true, "RECONNECTING", "CONNECTED", "RECONNECTING"],
    [true, "CONNECTED", "CONNECTING", "CONNECTING"],
  ] as const)("still surfaces a degraded feed %s / %s / %s as %s", (active, gateway, upstream, label) => {
    const html = header(active, gateway, upstream);
    expect(html).toContain(`Market feed ${label.toLowerCase()}`);
    expect(html).toContain(label);
  });

  it("shows no feed chip when the feed is healthy", () => {
    const html = header(true, "CONNECTED", "CONNECTED");
    expect(html).not.toContain("Market feed");
    expect(html).not.toContain("LIVE");
    // the session chip still carries the real state
    expect(html).toContain("Market session open");
  });
});
