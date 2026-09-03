/**
 * Canonical Market Quote Domain Model
 * Decoupled from any exchange or gateway-specific schema.
 */

export type RealtimeDirection = "up" | "down";

export interface RealtimePulse {
  /** Monotonic per-field counter. A changed value retriggers the CSS animation. */
  sequence: number;
  direction: RealtimeDirection;
  /** Wall-clock creation time prevents a later-mounted surface replaying an old flash. */
  startedAt?: number;
}

/**
 * Transient presentation metadata produced only by incremental realtime patches.
 * Full snapshots deliberately omit it so hydration/reconnects never flash as trades.
 */
export type RealtimePulseMap = Partial<Record<string, RealtimePulse>>;

export interface MarketQuote {
  symbol: string;
  instrumentType?: "STOCK" | "CW" | "INDEX";

  // Realtime Prices
  lastPrice: number | null;
  referencePrice: number | null;
  ceilingPrice: number | null;
  floorPrice: number | null;
  openPrice: number | null;
  highPrice: number | null;
  lowPrice: number | null;
  averagePrice: number | null;

  // Level 1 Best Bid & Ask
  bidPrice: number | null;
  bidQuantity: number | null;
  askPrice: number | null;
  askQuantity: number | null;

  // Level 2 & 3 Depth (Optional)
  bid2Price?: number | null;
  bid2Quantity?: number | null;
  ask2Price?: number | null;
  ask2Quantity?: number | null;
  bid3Price?: number | null;
  bid3Quantity?: number | null;
  ask3Price?: number | null;
  ask3Quantity?: number | null;

  // Volume & Value Aggregates
  tradedQuantity: number | null;
  totalVolume: number | null;
  tradingValue: number | null;
  priceChange: number | null;
  priceChangePercent: number | null;

  // Foreign Investor Statistics
  foreignBuy?: number | null;
  foreignSell?: number | null;
  foreignRemain?: number | null;
  foreignRoom?: number | null;

  // Timestamps
  exchangeTimestamp: number | null;
  sourceTimestamp: number | null;
  receivedTimestamp: number;

  realtimePulses?: RealtimePulseMap;
}
