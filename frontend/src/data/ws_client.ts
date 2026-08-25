/**
 * WebSocket client for connecting to the backend server
 */

import type { EquityRow, EquityPatch } from "@/tables/equity/types";

import type { IndexRow } from "@/tables/index/types";

type ServerToClient =
  | { type: "snapshot"; symbol: string; row: EquityRow; ts: number }
  | { type: "patch"; symbol: string; patch: EquityPatch; ts: number }
  | { type: "status"; connected: boolean; message: string }
  | { type: "trading_dates"; dates: string[] }
  | { type: "listed_volumes"; date: string; volumes: Record<string, number> }
  | { type: "index_update"; data: IndexRow; ts: number };

export interface WSClientCallbacks {
  onSnapshot: (symbol: string, row: EquityRow, ts?: number) => void;
  onPatch: (symbol: string, patch: EquityPatch, ts?: number) => void;
  onStatusChange: (connected: boolean, message: string) => void;
  onIndexUpdate?: (data: IndexRow, ts: number) => void;
  onTradingDates?: (dates: string[]) => void;
  onListedVolumes?: (date: string, volumes: Record<string, number>) => void;
}

export class WSClient {
  private ws: WebSocket | null = null;
  private callbacks: WSClientCallbacks;
  private reconnectTimer: number | null = null;
  private reconnectDelay = 3000;
  private url: string;

  constructor(url: string, callbacks: WSClientCallbacks) {
    this.url = url;
    this.callbacks = callbacks;
  }

  connect(): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      return;
    }

    console.log("[WS] Connecting to", this.url);
    this.ws = new WebSocket(this.url);

    this.ws.onopen = () => {
      console.log("[WS] Connected");
      this.callbacks.onStatusChange(true, "Connected");
    };

    this.ws.onmessage = (event) => {
      try {
        const msg: ServerToClient = JSON.parse(event.data);
        this.handleMessage(msg);
      } catch (err) {
        console.error("[WS] Parse error:", err);
      }
    };

    this.ws.onerror = (err) => {
      console.error("[WS] Error:", err);
    };

    this.ws.onclose = () => {
      console.log("[WS] Disconnected");
      this.callbacks.onStatusChange(false, "Disconnected");
      this.scheduleReconnect();
    };
  }

  private handleMessage(msg: ServerToClient): void {
    switch (msg.type) {
      case "snapshot":
        this.callbacks.onSnapshot(msg.symbol, msg.row, msg.ts);
        break;
      case "patch":
        this.callbacks.onPatch(msg.symbol, msg.patch, msg.ts);
        break;
      case "status":
        this.callbacks.onStatusChange(msg.connected, msg.message);
        break;
      case "index_update":
        this.callbacks.onIndexUpdate?.(msg.data, msg.ts);
        break;
      case "trading_dates":
        this.callbacks.onTradingDates?.(msg.dates);
        break;
      case "listed_volumes":
        this.callbacks.onListedVolumes?.(msg.date, msg.volumes);
        break;
    }
  }

  public send(msg: any): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg));
    }
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
    }

    console.log(`[WS] Reconnecting in ${this.reconnectDelay}ms...`);
    this.reconnectTimer = setTimeout(() => {
      this.connect();
    }, this.reconnectDelay) as any;
  }

  disconnect(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }

    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }
}

