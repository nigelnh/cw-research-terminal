import { describe, it, expect, beforeEach, vi } from "vitest";
import { BackendWebSocketClient } from "../data/backend/backend_websocket_client";

describe("BackendWebSocketClient - Correctness, Routing & Lifecycle Tests", () => {
  let client: BackendWebSocketClient;

  beforeEach(() => {
    client = new BackendWebSocketClient("ws://localhost:8501/ws/market");
  });

  it("1. Patch before initial snapshots: queues patch and merges cleanly when snapshot arrives", () => {
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
    expect(merged?.quote.lastPrice).toBe(1350);
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

    client.handleIncomingMessage({
      type: "patch",
      symbol: "CHPG2401",
      patch: { Symbol: "CHPG2401", Traded: 1.38, _ts_source: 5050 },
    });
    expect(client.getCoveredWarrant("CHPG2401")?.quote.lastPrice).toBe(1380);

    client.handleIncomingMessage({
      type: "patch",
      symbol: "CHPG2401",
      patch: { Symbol: "CHPG2401", Traded: 1.36, _ts_source: 5020 },
    });

    expect(client.getCoveredWarrant("CHPG2401")?.quote.lastPrice).toBe(1380);
  });

  it("4b. Out-of-order stock patches and snapshots cannot rewind the quote", () => {
    client.handleIncomingMessage({
      type: "snapshot",
      row: {
        Symbol: "HPG",
        InstrumentType: "STOCK",
        Traded: 22.1,
        _ts_source: 5000,
      },
    });
    client.handleIncomingMessage({
      type: "patch",
      symbol: "HPG",
      patch: { Traded: 22.3, _ts_source: 5050 },
    });
    client.handleIncomingMessage({
      type: "patch",
      symbol: "HPG",
      patch: { Traded: 22.2, _ts_source: 5020 },
    });
    client.handleIncomingMessage({
      type: "snapshot",
      row: {
        Symbol: "HPG",
        InstrumentType: "STOCK",
        Traded: 22.15,
        _ts_source: 5040,
      },
    });

    expect(client.getQuote("HPG")?.lastPrice).toBe(22_300);
    expect(client.getQuote("HPG")?.sourceTimestamp).toBe(5050);
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

    client.handleIncomingMessage({
      type: "snapshot",
      symbol: "CMWG2401",
      row: { Symbol: "CMWG2401", Traded: 1.50, _ts_source: 9000 },
    });

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

  it("8. Failed handshake does not mark gateway LIVE or upstream connected", () => {
    const errorClient = new BackendWebSocketClient("ws://localhost:8501/ws/market");
    expect(errorClient.getConnectionState()).toBe("DISCONNECTED");
    expect(errorClient.getUpstreamFeedState()).toBe("UNKNOWN");

    // Receiving gateway disconnected status frame
    errorClient.handleIncomingMessage({
      type: "status",
      gateway_connected: false,
      upstream_status: "UNAVAILABLE",
      connected: false,
    });

    expect(errorClient.getUpstreamFeedState()).toBe("DISCONNECTED");
  });

  it("9. Planned subscription count does not imply upstream live feed", () => {
    const newClient = new BackendWebSocketClient("ws://localhost:8501/ws/market");
    newClient.subscribeSymbols(["HPG", "NVL", "VHM", "CVHM2615", "CHPG2541"]);

    expect(newClient.getSubscribedSymbols().size).toBe(5);
    // Subscribed symbols exist, but upstream feed is still UNKNOWN until gateway connects and delivers ticks
    expect(newClient.getUpstreamFeedState()).toBe("UNKNOWN");
    expect(newClient.getAllQuotes().size).toBe(0);
  });

  it("10. Subscription payload after OPEN contains exactly requested primary symbols", () => {
    const sentMessages: string[] = [];
    const mockWs: any = {
      readyState: 1, // OPEN
      send: vi.fn((data: string) => sentMessages.push(data)),
      close: vi.fn(),
    };

    (client as any).ws = mockWs;
    client.subscribeSymbols(["HPG", "NVL", "VHM", "CVHM2615", "CHPG2541"]);

    expect(mockWs.send).toHaveBeenCalledTimes(1);
    const parsed = JSON.parse(sentMessages[0]);
    expect(parsed.type).toBe("subscribe");
    expect(parsed.symbols).toEqual(["HPG", "NVL", "VHM", "CVHM2615", "CHPG2541"]);
  });

  it("11. Sends a heartbeat and stops it on disconnect", () => {
    vi.useFakeTimers();
    const mockWs: any = {
      readyState: 1,
      send: vi.fn(),
      close: vi.fn(),
    };
    (client as any).ws = mockWs;
    (client as any).startHeartbeat();

    vi.advanceTimersByTime(20_000);
    expect(mockWs.send).toHaveBeenCalledWith(JSON.stringify({ type: "ping" }));

    client.disconnect();
    const calls = mockWs.send.mock.calls.length;
    vi.advanceTimersByTime(40_000);
    expect(mockWs.send).toHaveBeenCalledTimes(calls);
    vi.useRealTimers();
  });

  it("12. Same-price route hydration preserves the accepted analytics snapshot", () => {
    const row = {
      Symbol: "CHPG2625",
      Under_Symbol: "HPG",
      Under_Prc: 21.85,
      Traded: 0.57,
      Bid1_Prc: 0.56,
      Ask1_Prc: 0.57,
      _market_session_date: "2026-09-10",
      _ts_source: 10_000,
    };
    client.handleIncomingMessage({ type: "snapshot", row });
    client.handleIncomingMessage({
      type: "analytics_patch",
      symbol: "CHPG2625",
      analytics: {
        symbol: "CHPG2625",
        underlying_symbol: "HPG",
        session_date: "2026-09-10",
        calculated_at: "2026-09-10T10:00:00+07:00",
        is_available: true,
        iv_bid: 0.35,
        iv_trade: 0.36,
        iv_ask: 0.36,
        input_provenance: {
          underlying: { sessionDate: "2026-09-10" },
          trade: { sessionDate: "2026-09-10" },
          book: { sessionDate: "2026-09-10" },
        },
        model_inputs: {
          underlying_price: 21_850,
          market_last: 570,
          market_bid: 560,
          market_ask: 570,
        },
      },
    });
    const accepted = client.getCoveredWarrant("CHPG2625");

    client.handleIncomingMessage({
      type: "snapshot",
      row: { ...row, _ts_source: 11_000, Total_Vol: 999_000 },
    });
    const hydrated = client.getCoveredWarrant("CHPG2625");
    expect(hydrated?.analyticsSnapshot).toEqual(accepted?.analyticsSnapshot);
    expect(hydrated?.analyticsCalculatedAt).toBe(accepted?.analyticsCalculatedAt);
    expect(hydrated?.ivBid).toBe(0.35);
    expect(hydrated?.ivTrade).toBe(0.36);
    expect(hydrated?.ivAsk).toBe(0.36);

    client.handleIncomingMessage({
      type: "snapshot",
      row: { ...row, Bid1_Prc: 0.55, _ts_source: 12_000 },
    });
    expect(client.getCoveredWarrant("CHPG2625")?.analyticsSnapshot).toBeUndefined();
    expect(client.getCoveredWarrant("CHPG2625")?.ivBid).toBeNull();
  });

  it("13. Redis-restored analytics hydrate atomically with the initial quote", () => {
    const observed: Array<{ last: number | null; iv: number | null }> = [];
    client.onCoveredWarrantUpdate((cw) => {
      if (cw.symbol === "CHPG2625") {
        observed.push({ last: cw.quote.lastPrice, iv: cw.ivTrade });
      }
    });

    client.handleIncomingMessage({
      type: "snapshot",
      row: {
        Symbol: "CHPG2625",
        Under_Symbol: "HPG",
        Under_Prc: 21.85,
        Traded: 0.57,
        Bid1_Prc: 0.56,
        Ask1_Prc: 0.57,
        _market_session_date: "2026-09-10",
        analytics: {
          symbol: "CHPG2625",
          underlying_symbol: "HPG",
          session_date: "2026-09-10",
          calculated_at: "2026-09-10T10:00:00+07:00",
          is_available: true,
          iv_bid: 0.35,
          iv_trade: 0.36,
          iv_ask: 0.36,
          model_inputs: {
            underlying_price: 21_850,
            market_last: 570,
            market_bid: 560,
            market_ask: 570,
          },
        },
      },
    });

    expect(observed).toEqual([{ last: 570, iv: 0.36 }]);
    expect(client.getCoveredWarrant("CHPG2625")?.ivBid).toBe(0.35);
    expect(client.getCoveredWarrant("CHPG2625")?.ivAsk).toBe(0.36);
  });
});
