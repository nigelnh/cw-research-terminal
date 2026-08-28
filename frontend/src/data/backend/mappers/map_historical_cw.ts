import type { HistoricalBar, AdjustedComparisonPoint, UnderlyingClosePoint, IndexBar } from "@/domain/models";

/**
 * Maps raw records from GET /api/cw/data to canonical HistoricalBar.
 */
export function mapRawCWDataToHistoricalBar(item: any): HistoricalBar {
  return {
    symbol: String(item.symbol || item.ticker || "").toUpperCase(),
    date: item.date || item.trading_date || item.tradingdate || item.timestamp || "",
    open: typeof item.open === "number" ? item.open : (typeof item.Open === "number" ? item.Open : null),
    high: typeof item.high === "number" ? item.high : (typeof item.High === "number" ? item.High : null),
    low: typeof item.low === "number" ? item.low : (typeof item.Low === "number" ? item.Low : null),
    close: typeof item.close === "number" ? item.close : (typeof item.Close === "number" ? item.Close : null),
    volume: typeof item.volume === "number" ? item.volume : (typeof item.Volume === "number" ? item.Volume : null),
    referencePrice: typeof item.ref_price === "number" ? item.ref_price : (typeof item.referencePrice === "number" ? item.referencePrice : null),
    value: typeof item.total_match_val === "number" ? item.total_match_val : (typeof item.value === "number" ? item.value : null),
  };
}

/**
 * Maps raw records from GET /api/cw/comparison to AdjustedComparisonPoint.
 */
export function mapRawComparisonToAdjustedPoint(item: any): AdjustedComparisonPoint {
  return {
    symbol: String(item.stockcode || "").toUpperCase(),
    date: item.tradingdate || "",
    closePrice: typeof item.closeprice === "number" ? item.closeprice : null,
    basicPrice: typeof item.basicprice === "number" ? item.basicprice : null,
    adjustedRate: typeof item.adjustedrate === "number" ? item.adjustedrate : null,
    totalAdjustedRate: typeof item.totaladjustedrate === "number" ? item.totaladjustedrate : null,
    adjustedClosePrice: typeof item.adjustedcloseprice === "number" ? item.adjustedcloseprice : null,
  };
}

/**
 * Maps raw records from GET /api/v1/history/stocks/close to UnderlyingClosePoint.
 */
export function mapRawUnderlyingCloseToPoint(item: any): UnderlyingClosePoint {
  return {
    symbol: String(item.symbol || "").toUpperCase(),
    date: item.date || item.trading_date || "",
    close: typeof item.close === "number" ? item.close : null,
    rawClose: typeof item.rawClose === "number" ? item.rawClose : (typeof item.closeraw === "number" ? item.closeraw : null),
  };
}

/**
 * Maps raw records from GET /api/v1/history/index to IndexBar.
 */
export function mapRawIndexHistoryToBar(item: any): IndexBar {
  return {
    name: String(item.name || "VNINDEX").toUpperCase(),
    date: item.date || item.trading_date || "",
    open: typeof item.open === "number" ? item.open : null,
    high: typeof item.high === "number" ? item.high : null,
    low: typeof item.low === "number" ? item.low : null,
    close: typeof item.close === "number" ? item.close : null,
  };
}
