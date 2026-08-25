import { describe, it, expect } from "vitest";
import { BackendWebSocketClient } from "../data/backend/backend_websocket_client";
import { MockMarketDataProvider } from "../data/mock/mock_market_data_provider";

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

  it("4. Infers upstream feed is CONNECTED when receiving valid snapshots or ticks", () => {
    const client = new BackendWebSocketClient("ws://localhost:8787");
    expect(client.getUpstreamFeedState()).toBe("UNKNOWN");

    client.handleIncomingMessage({
      type: "snapshots",
      rows: [{ Symbol: "CHPG2401", Traded: 1.35, Strike_Prc: 28.0, Ratio: 2.0 }],
      ts: Date.now(),
    });

    expect(client.getUpstreamFeedState()).toBe("CONNECTED");
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

  it("6. MockMarketDataProvider preserves mock mode as Demo Data", () => {
    const mock = new MockMarketDataProvider();
    expect(mock.getConnectionState()).toBe("DISCONNECTED");
    expect(mock.getUpstreamFeedState()).toBe("UNKNOWN");

    mock.connect();
    // After connect, mock provider provides immediate local simulated feeds
    expect(mock.getUpstreamFeedState()).toBe("UNKNOWN"); // initial before timeout
  });
});
