import type { CoveredWarrant, MarketQuote } from "@/domain/models";

/**
 * Converts a price value from gateway thousand-VND transport to canonical raw VND.
 * Strictly protocol-driven (unconditional multiplication by 1000), NOT magnitude-based heuristic.
 * Example: 29.5 -> 29500, 1.35 -> 1350, 0.88 -> 880.
 */
export function normalizeTransportPriceToRawVnd(val: any): number | null {
  if (val === null || val === undefined) return null;
  const num = Number(val);
  if (isNaN(num)) return null;
  return Math.round(num * 1000);
}

/**
 * Converts Implied Volatility from gateway percentage transport to canonical decimal domain format.
 * Example: 32.5 (%) -> 0.325.
 * Sentinels (-1.0 no calculation, -2.0 solver divergence) map strictly to null.
 */
export function normalizeTransportIVToDecimal(val: any): number | null {
  if (val === null || val === undefined) return null;
  const num = Number(val);
  if (isNaN(num) || num < 0) return null;
  return Number((num / 100).toFixed(6));
}

/**
 * Normalizes raw gateway snapshot row into canonical MarketQuote model.
 */
export function mapRawSnapshotToQuote(raw: any): MarketQuote {
  const symbol = String(raw.Symbol || "").toUpperCase();
  return {
    symbol,
    lastPrice: normalizeTransportPriceToRawVnd(raw.Traded ?? raw.last_prc_t),
    referencePrice: normalizeTransportPriceToRawVnd(raw.Ref ?? raw.last_prc_t_1),
    ceilingPrice: normalizeTransportPriceToRawVnd(raw.Ceil),
    floorPrice: normalizeTransportPriceToRawVnd(raw.Floor),
    openPrice: normalizeTransportPriceToRawVnd(raw.Open_Prc),
    highPrice: normalizeTransportPriceToRawVnd(raw.High_Prc),
    lowPrice: normalizeTransportPriceToRawVnd(raw.Low_Prc),
    averagePrice: normalizeTransportPriceToRawVnd(raw.Avg_Prc),

    bidPrice: normalizeTransportPriceToRawVnd(raw.Bid1_Prc),
    bidQuantity: typeof raw.Bid1_Qty === "number" ? raw.Bid1_Qty : null,
    askPrice: normalizeTransportPriceToRawVnd(raw.Ask1_Prc),
    askQuantity: typeof raw.Ask1_Qty === "number" ? raw.Ask1_Qty : null,

    bid2Price: normalizeTransportPriceToRawVnd(raw.Bid2_Prc),
    bid2Quantity: typeof raw.Bid2_Qty === "number" ? raw.Bid2_Qty : null,
    ask2Price: normalizeTransportPriceToRawVnd(raw.Ask2_Prc),
    ask2Quantity: typeof raw.Ask2_Qty === "number" ? raw.Ask2_Qty : null,
    bid3Price: normalizeTransportPriceToRawVnd(raw.Bid3_Prc),
    bid3Quantity: typeof raw.Bid3_Qty === "number" ? raw.Bid3_Qty : null,
    ask3Price: normalizeTransportPriceToRawVnd(raw.Ask3_Prc),
    ask3Quantity: typeof raw.Ask3_Qty === "number" ? raw.Ask3_Qty : null,

    tradedQuantity: typeof raw.Traded_Qty === "number" ? raw.Traded_Qty : null,
    totalVolume: typeof raw.Total_Vol === "number" ? raw.Total_Vol : (typeof raw.Total_Volume === "number" ? raw.Total_Volume : null),
    tradingValue: normalizeTransportPriceToRawVnd(raw.Trading_Val),

    priceChange: normalizeTransportPriceToRawVnd(raw.Change),
    priceChangePercent: typeof raw.ChangePercent === "number" ? raw.ChangePercent : (typeof raw.Change_Percent === "number" ? raw.Change_Percent : null),

    exchangeTimestamp: raw.ExchangeTime ? Number(raw.ExchangeTime) : (raw.Exchange_Time ? Number(raw.Exchange_Time) : null),
    sourceTimestamp: raw._ts_source ? Number(raw._ts_source) : null,
    receivedTimestamp: Date.now(),
  };
}

/**
 * Normalizes raw gateway snapshot row into canonical CoveredWarrant & MarketQuote models.
 */
export function mapRawSnapshotToCoveredWarrant(raw: any): CoveredWarrant {
  const symbol = String(raw.Symbol || "").toUpperCase();
  const underlyingSymbol = String(raw.Under_Symbol || raw.Underlying || "").toUpperCase();
  
  const rawUnderPrc = raw.Under_Prc !== undefined ? raw.Under_Prc : raw.under_prc;
  const underlyingPrice = normalizeTransportPriceToRawVnd(rawUnderPrc);

  const rawStrikePrc = raw.Strike_Prc !== undefined ? raw.Strike_Prc : (raw.strike_prc !== undefined ? raw.strike_prc : raw.Exercise_Prc);
  const strikePrice = normalizeTransportPriceToRawVnd(rawStrikePrc) ?? 0;

  // Exercise ratio is dimensionless (e.g. 2.0 for 2:1 ratio) - DO NOT MULTIPLY, missing ratio is null
  const exerciseRatio = typeof raw.Ratio === "number" ? raw.Ratio : (typeof raw.ratio === "number" ? raw.ratio : (typeof raw.Exercise_Ratio === "number" ? raw.Exercise_Ratio : null));

  const lastTradingDate = raw.LastTradingDate || raw.last_trading_date || null;
  const maturityDate = raw.MaturityDate || raw.maturity_date || raw.Expiry || "";

  // Canonical Quote with all prices converted from thousand-VND to raw VND
  const quote = mapRawSnapshotToQuote(raw);

  // Vol1 (Ask), Vol2 (Trade/Mid), Vol3 (Bid) converted from percentage to canonical decimal
  const ivAsk = normalizeTransportIVToDecimal(raw.Vol1 ?? raw.iv_ask);
  const ivTrade = normalizeTransportIVToDecimal(raw.Vol2 ?? raw.iv_trade);
  const ivBid = normalizeTransportIVToDecimal(raw.Vol3 ?? raw.iv_bid);

  return {
    symbol,
    issuer: raw.Issuer || raw.issuer || null,
    underlyingSymbol,
    underlyingPrice,
    strikePrice,
    exerciseRatio: exerciseRatio as any,
    lastTradingDate,
    maturityDate,
    listedVolume: typeof raw.Listed_Vol === "number" ? raw.Listed_Vol : null,
    quote,
    ivAsk,
    ivTrade,
    ivBid,
  };
}
