import type { CoveredWarrant, MarketQuote } from "@/domain/models";
import {
  normalizeTransportPriceToRawVnd,
  normalizeTransportIVToDecimal,
  normalizeTransportPrice,
  instrumentTypeOf,
} from "./map_snapshot";
import { mergeRealtimePulses } from "./realtime_pulse";

export interface PatchApplyOptions {
  /** False while establishing a baseline after initial connect/reconnect/session rollover. */
  emitPulses?: boolean;
}

/**
 * Applies an incremental gateway market-data patch onto a MarketQuote model.
 */
export function applyRawPatchToQuote(
  existing: MarketQuote | undefined,
  symbol: string,
  patch: any,
  sourceTs?: number | null,
  options: PatchApplyOptions = {},
): MarketQuote {
  const base: MarketQuote = existing || {
    symbol,
    lastPrice: null,
    referencePrice: null,
    ceilingPrice: null,
    floorPrice: null,
    openPrice: null,
    highPrice: null,
    lowPrice: null,
    averagePrice: null,
    bidPrice: null,
    bidQuantity: null,
    askPrice: null,
    askQuantity: null,
    tradedQuantity: null,
    totalVolume: null,
    tradingValue: null,
    priceChange: null,
    priceChangePercent: null,
    exchangeTimestamp: null,
    sourceTimestamp: sourceTs || null,
    receivedTimestamp: Date.now(),
  };

  const instrumentType = instrumentTypeOf(
    { ...patch, Symbol: symbol },
    existing,
  );
  const price = (v: any) => normalizeTransportPrice(v, instrumentType);
  const q: MarketQuote = {
    ...base,
    instrumentType,
    receivedTimestamp: Date.now(),
  };

  if (patch.Traded !== undefined) q.lastPrice = price(patch.Traded);
  if (patch.Ref !== undefined) q.referencePrice = price(patch.Ref);
  if (patch.Ceil !== undefined) q.ceilingPrice = price(patch.Ceil);
  if (patch.Floor !== undefined) q.floorPrice = price(patch.Floor);
  if (patch.Open_Prc !== undefined) q.openPrice = price(patch.Open_Prc);
  if (patch.High_Prc !== undefined) q.highPrice = price(patch.High_Prc);
  if (patch.Low_Prc !== undefined) q.lowPrice = price(patch.Low_Prc);
  if (patch.Avg_Prc !== undefined) q.averagePrice = price(patch.Avg_Prc);

  // Depth Level 1
  if (patch.Bid1_Prc !== undefined) q.bidPrice = price(patch.Bid1_Prc);
  if (patch.Bid1_Qty !== undefined) q.bidQuantity = patch.Bid1_Qty;
  if (patch.Ask1_Prc !== undefined) q.askPrice = price(patch.Ask1_Prc);
  if (patch.Ask1_Qty !== undefined) q.askQuantity = patch.Ask1_Qty;

  // Depth Level 2
  if (patch.Bid2_Prc !== undefined) q.bid2Price = price(patch.Bid2_Prc);
  if (patch.Bid2_Qty !== undefined) q.bid2Quantity = patch.Bid2_Qty;
  if (patch.Ask2_Prc !== undefined) q.ask2Price = price(patch.Ask2_Prc);
  if (patch.Ask2_Qty !== undefined) q.ask2Quantity = patch.Ask2_Qty;

  // Depth Level 3
  if (patch.Bid3_Prc !== undefined) q.bid3Price = price(patch.Bid3_Prc);
  if (patch.Bid3_Qty !== undefined) q.bid3Quantity = patch.Bid3_Qty;
  if (patch.Ask3_Prc !== undefined) q.ask3Price = price(patch.Ask3_Prc);
  if (patch.Ask3_Qty !== undefined) q.ask3Quantity = patch.Ask3_Qty;

  // Volumes & Values
  if (patch.Traded_Qty !== undefined) q.tradedQuantity = patch.Traded_Qty;
  if (patch.Total_Vol !== undefined) q.totalVolume = patch.Total_Vol;
  if (patch.Trading_Val !== undefined)
    q.tradingValue = price(patch.Trading_Val);
  const rawChange = patch.change !== undefined ? patch.change : patch.Change;
  if (rawChange !== undefined) q.priceChange = price(rawChange);
  if (patch.ChangePercent !== undefined)
    q.priceChangePercent = patch.ChangePercent;

  // Timestamps
  if (patch.ExchangeTime !== undefined)
    q.exchangeTimestamp = Number(patch.ExchangeTime);
  if (patch._ts_source !== undefined) {
    q.sourceTimestamp = Number(patch._ts_source);
    if (patch._ts_trade === undefined) q.tradeTimestamp = Number(patch._ts_source);
  }
  if (patch._ts_trade !== undefined) q.tradeTimestamp = Number(patch._ts_trade);
  if (patch._ts_book !== undefined) q.bookTimestamp = Number(patch._ts_book);
  if (patch._ts_reference !== undefined) q.referenceTimestamp = Number(patch._ts_reference);
  if (patch._received_trade !== undefined) q.tradeReceivedTimestamp = Number(patch._received_trade);
  if (patch._received_book !== undefined) q.bookReceivedTimestamp = Number(patch._received_book);
  if (patch._market_session_date !== undefined) q.marketSessionDate = patch._market_session_date;
  if (patch._reference_session_date !== undefined) q.referenceSessionDate = patch._reference_session_date;
  if (patch._provider_market_status !== undefined) q.providerMarketStatus = patch._provider_market_status;

  const touched: string[] = [];
  const fieldByWireKey: Record<string, string> = {
    Traded: "lastPrice",
    Open_Prc: "openPrice",
    High_Prc: "highPrice",
    Low_Prc: "lowPrice",
    Avg_Prc: "averagePrice",
    Bid1_Prc: "bidPrice",
    Bid1_Qty: "bidQuantity",
    Ask1_Prc: "askPrice",
    Ask1_Qty: "askQuantity",
    Bid2_Prc: "bid2Price",
    Bid2_Qty: "bid2Quantity",
    Ask2_Prc: "ask2Price",
    Ask2_Qty: "ask2Quantity",
    Bid3_Prc: "bid3Price",
    Bid3_Qty: "bid3Quantity",
    Ask3_Prc: "ask3Price",
    Ask3_Qty: "ask3Quantity",
    Traded_Qty: "tradedQuantity",
    Total_Vol: "totalVolume",
    Trading_Val: "tradingValue",
    ChangePercent: "priceChangePercent",
  };
  for (const [wire, field] of Object.entries(fieldByWireKey)) {
    if (patch[wire] !== undefined) touched.push(field);
  }
  if (rawChange !== undefined) touched.push("priceChange");
  q.realtimePulses = mergeRealtimePulses(
    base.realtimePulses,
    base as unknown as Record<string, number | null | undefined>,
    q as unknown as Record<string, number | null | undefined>,
    touched,
    options.emitPulses !== false,
  );

  return q;
}

/**
 * Applies an incremental gateway market-data patch onto an existing CoveredWarrant model.
 * Performs thousand-VND to raw VND unit conversion protocol-driven without magnitude heuristics.
 */
export function applyRawPatchToCoveredWarrant(
  existing: CoveredWarrant,
  patch: any,
  options: PatchApplyOptions = {},
): CoveredWarrant {
  const q = applyRawPatchToQuote(
    existing.quote,
    existing.symbol,
    patch,
    existing.quote.sourceTimestamp,
    options,
  );

  // Volatilities
  const ivAsk =
    patch.Vol1 !== undefined
      ? normalizeTransportIVToDecimal(patch.Vol1)
      : existing.ivAsk;
  const ivTrade =
    patch.Vol2 !== undefined
      ? normalizeTransportIVToDecimal(patch.Vol2)
      : existing.ivTrade;
  const ivBid =
    patch.Vol3 !== undefined
      ? normalizeTransportIVToDecimal(patch.Vol3)
      : existing.ivBid;

  const underlyingPrice =
    patch.Under_Prc !== undefined
      ? normalizeTransportPriceToRawVnd(patch.Under_Prc)
      : existing.underlyingPrice;

  const updated = {
    ...existing,
    underlyingPrice,
    quote: q,
    ivAsk,
    ivTrade,
    ivBid,
  };
  const touched = [
    ...(patch.Vol1 !== undefined ? ["ivAsk"] : []),
    ...(patch.Vol2 !== undefined ? ["ivTrade"] : []),
    ...(patch.Vol3 !== undefined ? ["ivBid"] : []),
    ...(patch.Under_Prc !== undefined ? ["underlyingPrice"] : []),
  ];
  updated.realtimePulses = mergeRealtimePulses(
    existing.realtimePulses,
    existing as unknown as Record<string, number | null | undefined>,
    updated as unknown as Record<string, number | null | undefined>,
    touched,
    options.emitPulses !== false,
  );
  return updated;
}
