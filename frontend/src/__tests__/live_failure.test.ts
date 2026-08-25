import { describe, it, expect } from "vitest";
import { createProviders } from "../data/providers/provider_factory";
import { BackendMarketDataProvider } from "../data/backend/backend_market_data_provider";
import { BackendWebSocketClient } from "../data/backend/backend_websocket_client";

describe("Live Mode - Failure Handling & Lifecycle Integrity", () => {
  it("uses BackendMarketDataProvider in live mode without silent mock fallback", () => {
    const liveSuite = createProviders("live");
    expect(liveSuite.marketData).toBeInstanceOf(BackendMarketDataProvider);

    // Initial state in live mode must be empty (0 warrants), never pre-hydrated with mock data
    const initialWarrants = liveSuite.marketData.getAllCoveredWarrants();
    expect(initialWarrants.size).toBe(0);
  });

  it("handles live gateway disconnection cleanly and maintains non-fallback state", () => {
    const client = new BackendWebSocketClient("ws://localhost:9999");
    const states: string[] = [];

    const unsub = client.onConnectionStateChange((state) => states.push(state));
    expect(client.getConnectionState()).toBe("DISCONNECTED");
    expect(client.getAllCoveredWarrants().size).toBe(0);

    unsub();
  });

  it("cleans up listeners on unsubscribe without leaking memory", () => {
    const client = new BackendWebSocketClient("ws://localhost:8787");
    let callCount = 0;

    const unsub = client.onCoveredWarrantUpdate(() => {
      callCount++;
    });

    client.handleIncomingMessage({
      type: "snapshot",
      symbol: "CHPG2401",
      row: { Symbol: "CHPG2401", Traded: 1.35 },
    });
    expect(callCount).toBe(1);

    // Unsubscribe listener
    unsub();

    client.handleIncomingMessage({
      type: "snapshot",
      symbol: "CHPG2401",
      row: { Symbol: "CHPG2401", Traded: 1.36 },
    });
    // Should NOT receive updates after unsubscribe
    expect(callCount).toBe(1);
  });

  it("does not create duplicate updates when registering identical listeners", () => {
    const client = new BackendWebSocketClient("ws://localhost:8787");
    const received: string[] = [];
    const listener = (cw: any) => received.push(cw.symbol);

    const unsub1 = client.onCoveredWarrantUpdate(listener);
    const unsub2 = client.onCoveredWarrantUpdate(listener); // Set will deduplicate

    client.handleIncomingMessage({
      type: "snapshot",
      symbol: "CHPG2401",
      row: { Symbol: "CHPG2401", Traded: 1.35 },
    });

    // Both unsubs registered same listener, it should only be called once per event
    expect(received.length).toBe(1);

    unsub1();
    unsub2();
  });
});
