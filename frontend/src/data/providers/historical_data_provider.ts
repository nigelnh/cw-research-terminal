import type { HistoricalBar, UnderlyingClosePoint, AdjustedComparisonPoint, IndexBar } from "@/domain/models";

export interface DateRange {
  fromDate: string; // YYYY-MM-DD
  toDate: string;   // YYYY-MM-DD
}

export interface HistoricalDataProvider {
  getHistoricalWarrantBars(symbol: string, range: DateRange): Promise<HistoricalBar[]>;
  getUnderlyingCloseHistory(symbol: string, range: DateRange): Promise<UnderlyingClosePoint[]>;
  getAdjustedUnderlyingComparison(stockCode: string, range: DateRange): Promise<AdjustedComparisonPoint[]>;
  getIndexHistory(name: string, range: DateRange): Promise<IndexBar[]>;
}
