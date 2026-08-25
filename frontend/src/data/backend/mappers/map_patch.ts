import type { CoveredWarrant, MarketQuote } from "@/domain/models";
import { normalizeTransportPriceToRawVnd, normalizeTransportIVToDecimal } from "./map_snapshot";

/**
 * Applies an incremental gateway market-data patch onto an existing CoveredWarrant model.
 * Performs thousand-VND to raw VND unit conversion protocol-driven without magnitude heuristics.
 */
export function applyRawPatchToCoveredWarrant(existing: CoveredWarrant, patch: any): CoveredWarrant {
  const q: MarketQuote = { ...existing.quote, receivedTimestamp: Date.now() };

  if (patch.Traded !== undefined) q.lastPrice = normalizeTransportPriceToRawVnd(patch.Traded);
  if (patch.Ref !== undefined) q.referencePrice = normalizeTransportPriceToRawVnd(patch.Ref);
  if (patch.Ceil !== undefined) q.ceilingPrice = normalizeTransportPriceToRawVnd(patch.Ceil);
  if (patch.Floor !== undefined) q.floorPrice = normalizeTransportPriceToRawVnd(patch.Floor);
  if (patch.Open_Prc !== undefined) q.openPrice = normalizeTransportPriceToRawVnd(patch.Open_Prc);
  if (patch.High_Prc !== undefined) q.highPrice = normalizeTransportPriceToRawVnd(patch.High_Prc);
  if (patch.Low_Prc !== undefined) q.lowPrice = normalizeTransportPriceToRawVnd(patch.Low_Prc);
  if (patch.Avg_Prc !== undefined) q.averagePrice = normalizeTransportPriceToRawVnd(patch.Avg_Prc);

  // Depth Level 1
  if (patch.Bid1_Prc !== undefined) q.bidPrice = normalizeTransportPriceToRawVnd(patch.Bid1_Prc);
  if (patch.Bid1_Qty !== undefined) q.bidQuantity = patch.Bid1_Qty;
  if (patch.Ask1_Prc !== undefined) q.askPrice = normalizeTransportPriceToRawVnd(patch.Ask1_Prc);
  if (patch.Ask1_Qty !== undefined) q.askQuantity = patch.Ask1_Qty;

  // Depth Level 2
  if (patch.Bid2_Prc !== undefined) q.bid2Price = normalizeTransportPriceToRawVnd(patch.Bid2_Prc);
  if (patch.Bid2_Qty !== undefined) q.bid2Quantity = patch.Bid2_Qty;
  if (patch.Ask2_Prc !== undefined) q.ask2Price = normalizeTransportPriceToRawVnd(patch.Ask2_Prc);
  if (patch.Ask2_Qty !== undefined) q.ask2Quantity = patch.Ask2_Qty;

  // Depth Level 3
  if (patch.Bid3_Prc !== undefined) q.bid3Price = normalizeTransportPriceToRawVnd(patch.Bid3_Prc);
  if (patch.Bid3_Qty !== undefined) q.bid3Quantity = patch.Bid3_Qty;
  if (patch.Ask3_Prc !== undefined) q.ask3Price = normalizeTransportPriceToRawVnd(patch.Ask3_Prc);
  if (patch.Ask3_Qty !== undefined) q.ask3Quantity = patch.Ask3_Qty;

  // Volumes & Values
  if (patch.Traded_Qty !== undefined) q.tradedQuantity = patch.Traded_Qty;
  if (patch.Total_Vol !== undefined) q.totalVolume = patch.Total_Vol;
  if (patch.Trading_Val !== undefined) q.tradingValue = normalizeTransportPriceToRawVnd(patch.Trading_Val);
  if (patch.Change !== undefined) q.priceChange = normalizeTransportPriceToRawVnd(patch.Change);
  if (patch.ChangePercent !== undefined) q.priceChangePercent = patch.ChangePercent;

  // Timestamps
  if (patch.ExchangeTime !== undefined) q.exchangeTimestamp = Number(patch.ExchangeTime);
  if (patch._ts_source !== undefined) q.sourceTimestamp = Number(patch._ts_source);

  // Volatilities
  const ivAsk = patch.Vol1 !== undefined ? normalizeTransportIVToDecimal(patch.Vol1) : existing.ivAsk;
  const ivTrade = patch.Vol2 !== undefined ? normalizeTransportIVToDecimal(patch.Vol2) : existing.ivTrade;
  const ivBid = patch.Vol3 !== undefined ? normalizeTransportIVToDecimal(patch.Vol3) : existing.ivBid;

  const underlyingPrice = patch.Under_Prc !== undefined 
    ? normalizeTransportPriceToRawVnd(patch.Under_Prc) 
    : existing.underlyingPrice;

  return {
    ...existing,
    underlyingPrice,
    quote: q,
    ivAsk,
    ivTrade,
    ivBid,
  };
}
