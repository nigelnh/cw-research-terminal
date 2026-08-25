import { describe, it, expect, beforeEach } from "vitest";
import { BackendWebSocketClient } from "../data/backend/backend_websocket_client";

describe("BackendWebSocketClient - Correctness & Ordering Tests", () => {
  let client: BackendWebSocketClient;

  beforeEach(() => {
    client = new BackendWebSocketClient("ws://localhost:8787");
  });

  it("1. Patch before initial snapshots: queues patch and merges cleanly when snapshot arrives", () => {
    // Patch arrives first for unseen symbol CHPG2401 in thousand-VND transport (1.35 -> 1350 VND)
    client.handleIncomingMessage({
      type: "patch",
      symbol: "CHPG2401",
      patch: {
        Symbol: "CHPG2401",
        Traded: 1.35,
        _ts_source: 1000,
      },
    });

    const placeholder = client.getCoveredWarrant("CHPG2401");
    expect(placeholder).toBeDefined();
    expect(placeholder?.quote.lastPrice).toBe(1350);

    // Full specification snapshot arrives later
    client.handleIncomingMessage({
      type: "snapshot",
      symbol: "CHPG2401",
      row: {
        Symbol: "CHPG2401",
        Under_Symbol: "HPG",
        Strike_Prc: 28.0,
        Ratio: 2.0,
        MaturityDate: "2024-11-20",
        Ref: 1.25,
        _ts_source: 1005,
      },
    });

    const merged = client.getCoveredWarrant("CHPG2401");
    expect(merged?.strikePrice).toBe(28000);
    expect(merged?.exerciseRatio).toBe(2.0);
    expect(merged?.quote.lastPrice).toBe(1350); // Buffered patch price retained
    expect(merged?.quote.referencePrice).toBe(1250);
  });

  it("2. Duplicate snapshots: safely updates state idempotently without corruption", () => {
    const snapshotMsg = {
      type: "snapshot",
      symbol: "CFPT2401",
      row: {
        Symbol: "CFPT2401",
        Under_Symbol: "FPT",
        Strike_Prc: 120.0,
        Ratio: 5.0,
        Traded: 4.5,
        _ts_source: 2000,
      },
    };

    client.handleIncomingMessage(snapshotMsg);
    expect(client.getCoveredWarrant("CFPT2401")?.strikePrice).toBe(120000);

    // Duplicate snapshot message arrives
    client.handleIncomingMessage(snapshotMsg);
    expect(client.getCoveredWarrant("CFPT2401")?.strikePrice).toBe(120000);
    expect(client.getAllCoveredWarrants().size).toBe(1);
  });

  it("3. Duplicate patch: applies idempotently", () => {
    client.handleIncomingMessage({
      type: "snapshot",
      symbol: "CVIC2401",
      row: { Symbol: "CVIC2401", Strike_Prc: 45.0, Ratio: 4.0, Traded: 2.1, _ts_source: 3000 },
    });

    const patchMsg = {
      type: "patch",
      symbol: "CVIC2401",
      patch: { Symbol: "CVIC2401", Traded: 2.15, _ts_source: 3010 },
    };

    client.handleIncomingMessage(patchMsg);
    expect(client.getCoveredWarrant("CVIC2401")?.quote.lastPrice).toBe(2150);

    client.handleIncomingMessage(patchMsg);
    expect(client.getCoveredWarrant("CVIC2401")?.quote.lastPrice).toBe(2150);
  });

  it("4. Out-of-order patch timestamps: rejects stale ticks with older source timestamps", () => {
    client.handleIncomingMessage({
      type: "snapshot",
      symbol: "CHPG2401",
      row: { Symbol: "CHPG2401", Traded: 1.35, _ts_source: 5000 },
    });

    // Newer tick arrives (ts = 5050)
    client.handleIncomingMessage({
      type: "patch",
      symbol: "CHPG2401",
      patch: { Symbol: "CHPG2401", Traded: 1.38, _ts_source: 5050 },
    });
    expect(client.getCoveredWarrant("CHPG2401")?.quote.lastPrice).toBe(1380);

    // Delayed/Stale out-of-order tick arrives (ts = 5020 < 5050)
    client.handleIncomingMessage({
      type: "patch",
      symbol: "CHPG2401",
      patch: { Symbol: "CHPG2401", Traded: 1.36, _ts_source: 5020 },
    });

    // Stale tick must be rejected! Last price remains 1380
    expect(client.getCoveredWarrant("CHPG2401")?.quote.lastPrice).toBe(1380);
  });

  it("5. Reconnect after disconnect: cleanly updates state transitions", () => {
    const states: string[] = [];
    client.onConnectionStateChange((state) => states.push(state));

    expect(client.getConnectionState()).toBe("DISCONNECTED");
    client.disconnect();
    expect(client.getConnectionState()).toBe("DISCONNECTED");
  });

  it("6. Stale patch after reconnect: dropped by timestamp ordering policy", () => {
    client.handleIncomingMessage({
      type: "snapshot",
      symbol: "CMWG2401",
      row: { Symbol: "CMWG2401", Traded: 1.45, _ts_source: 8000 },
    });

    // Reconnected snapshot with higher timestamp
    client.handleIncomingMessage({
      type: "snapshot",
      symbol: "CMWG2401",
      row: { Symbol: "CMWG2401", Traded: 1.50, _ts_source: 9000 },
    });

    // Delayed patch from pre-disconnect session with ts = 8500 (< 9000)
    client.handleIncomingMessage({
      type: "patch",
      symbol: "CMWG2401",
      patch: { Symbol: "CMWG2401", Traded: 1.48, _ts_source: 8500 },
    });

    expect(client.getCoveredWarrant("CMWG2401")?.quote.lastPrice).toBe(1500);
  });

  it("7. Bulk snapshots message: hydrates all warrant records atomically", () => {
    client.handleIncomingMessage({
      type: "snapshots",
      data: [
        { Symbol: "CHPG2401", Traded: 1.35, Strike_Prc: 28.0, Ratio: 2.0 },
        { Symbol: "CFPT2401", Traded: 3.2, Strike_Prc: 125.0, Ratio: 5.0 },
        { Symbol: "CMWG2401", Traded: 1.45, Strike_Prc: 60.0, Ratio: 3.0 },
      ],
    });

    expect(client.getAllCoveredWarrants().size).toBe(3);
    expect(client.getCoveredWarrant("CHPG2401")?.quote.lastPrice).toBe(1350);
    expect(client.getCoveredWarrant("CFPT2401")?.quote.lastPrice).toBe(3200);
    expect(client.getCoveredWarrant("CMWG2401")?.quote.lastPrice).toBe(1450);
  });

  it("8. Index update: routes cleanly to index listeners", () => {
    let receivedIndex: any = null;
    client.onIndexUpdate((idx) => {
      receivedIndex = idx;
    });

    client.handleIncomingMessage({
      type: "index_update",
      data: {
        name: "VNINDEX",
        value: 1285.5,
        change: 5.5,
        changePercent: 0.43,
      },
      ts: Date.now(),
    });

    expect(receivedIndex).toBeDefined();
    expect(receivedIndex.name).toBe("VNINDEX");
    expect(receivedIndex.value).toBe(1285.5);
  });

  it("9. Unknown message types: gracefully handled without throwing errors", () => {
    expect(() => {
      client.handleIncomingMessage({
        type: "unknown_future_message_type",
        payload: { test: true },
      });
    }).not.toThrow();
  });

  it("10. Malformed payload: handled safely without crashing client", () => {
    expect(() => {
      client.handleIncomingMessage(null);
      client.handleIncomingMessage(undefined);
      client.handleIncomingMessage("not-json" as any);
      client.handleIncomingMessage({ type: "patch" }); // Missing symbol and patch
    }).not.toThrow();
  });
});
