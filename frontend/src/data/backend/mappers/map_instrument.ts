import type { CoveredWarrant, MarketQuote } from "@/domain/models";

/**
 * Maps CW specification response from GET /api/v1/instruments/cw/active or /api/cw/market.
 */
export function mapInstrumentToCoveredWarrant(item: any): CoveredWarrant {
  const symbol = String(item.symbol || item.SYMBOL || "").toUpperCase();
  const underlyingSymbol = String(item.underlyingSymbol || item.underlying_symbol || item.UNDERLYING_SYMBOL || "").toUpperCase();

  const emptyQuote: MarketQuote = {
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
    sourceTimestamp: null,
    receivedTimestamp: Date.now(),
  };

  return {
    symbol,
    issuer: item.issuer || item.issuer_name || item.ISSUER_NAME || null,
    underlyingSymbol,
    underlyingPrice: null,
    strikePrice: typeof item.strike_price === "number" ? item.strike_price : (typeof item.strikePrice === "number" ? item.strikePrice : (typeof item.exercise_price === "number" ? item.exercise_price : parseFloat(item.strike_price || item.exercise_price || "0"))),
    exerciseRatio: typeof item.exercise_ratio === "number" ? item.exercise_ratio : (typeof item.exerciseRatio === "number" ? item.exerciseRatio : parseFloat(item.exercise_ratio || item.exerciseRatio || "1")),
    lastTradingDate: item.lastTradingDate || item.last_trading_date || item.LAST_TRADING_DATE || null,
    maturityDate: item.maturityDate || item.maturity_date || item.MATURITY_DATE || "",
    quote: emptyQuote,
    ivAsk: null,
    ivTrade: null,
    ivBid: null,
    listedVolume: item.listedVolume || item.listed_volume || null,
    outstandingVolume: null,
  };
}
