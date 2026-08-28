import type { HistoricalDataProvider, DateRange } from "@/data/providers";
import type { HistoricalBar, UnderlyingClosePoint, AdjustedComparisonPoint, IndexBar } from "@/domain/models";
import cwHistoryFixtures from "./cw_history.json";
import underlyingHistoryFixtures from "./underlying_history.json";
import indexHistoryFixtures from "./index_history.json";

export class MockHistoricalDataProvider implements HistoricalDataProvider {
  async getHistoricalWarrantBars(symbol: string, range: DateRange): Promise<HistoricalBar[]> {
    const sym = symbol.toUpperCase();
    const filtered = (cwHistoryFixtures as HistoricalBar[]).filter(
      (b) => b.symbol === sym && b.date >= range.fromDate && b.date <= range.toDate
    );
    if (filtered.length > 0) return filtered;
    return (cwHistoryFixtures as HistoricalBar[]).filter((b) => b.symbol === sym);
  }

  async getUnderlyingCloseHistory(symbol: string, range: DateRange): Promise<UnderlyingClosePoint[]> {
    const sym = symbol.toUpperCase();
    const filtered = (underlyingHistoryFixtures as UnderlyingClosePoint[]).filter(
      (u) => u.symbol === sym && u.date >= range.fromDate && u.date <= range.toDate
    );
    if (filtered.length > 0) return filtered;
    return (underlyingHistoryFixtures as UnderlyingClosePoint[]).filter((u) => u.symbol === sym);
  }

  async getAdjustedUnderlyingComparison(stockCode: string, range: DateRange): Promise<AdjustedComparisonPoint[]> {
    const sym = stockCode.toUpperCase();
    const stockHistory = (underlyingHistoryFixtures as UnderlyingClosePoint[]).filter(
      (u) => u.symbol === sym && u.date >= range.fromDate && u.date <= range.toDate
    );

    return stockHistory.map((s) => ({
      symbol: s.symbol,
      date: s.date,
      closePrice: s.close ? s.close / 1000 : null,
      basicPrice: s.close ? s.close / 1000 : null,
      adjustedRate: 1.0,
      totalAdjustedRate: 1.0,
      adjustedClosePrice: s.close ? s.close / 1000 : null,
    }));
  }

  async getIndexHistory(name: string, range: DateRange): Promise<IndexBar[]> {
    const targetName = name.toUpperCase();
    return (indexHistoryFixtures as IndexBar[]).filter(
      (i) => i.name === targetName && i.date >= range.fromDate && i.date <= range.toDate
    );
  }
}

export const mockHistoricalDataProvider = new MockHistoricalDataProvider();
