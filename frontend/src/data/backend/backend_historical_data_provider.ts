import type { HistoricalDataProvider, DateRange } from "@/data/providers";
import type { HistoricalBar, UnderlyingClosePoint, AdjustedComparisonPoint, IndexBar } from "@/domain/models";
import { BackendClient, backendClient } from "./backend_client";
import {
  mapRawCWDataToHistoricalBar,
  mapRawComparisonToAdjustedPoint,
  mapRawUnderlyingCloseToPoint,
  mapRawIndexHistoryToBar,
} from "./mappers";

export class BackendHistoricalDataProvider implements HistoricalDataProvider {
  private client: BackendClient;

  constructor(client?: BackendClient) {
    this.client = client || backendClient;
  }

  async getHistoricalWarrantBars(symbol: string, range: DateRange): Promise<HistoricalBar[]> {
    const raw = await this.client.getHistoricalCWData(symbol, range.fromDate, range.toDate);
    return raw.map(mapRawCWDataToHistoricalBar);
  }

  async getUnderlyingCloseHistory(symbol: string, range: DateRange): Promise<UnderlyingClosePoint[]> {
    const raw = await this.client.getStockCloseHistory(symbol, range.fromDate, range.toDate);
    return raw.map(mapRawUnderlyingCloseToPoint);
  }

  async getAdjustedUnderlyingComparison(stockCode: string, range: DateRange): Promise<AdjustedComparisonPoint[]> {
    const raw = await this.client.getComparison(stockCode, range.fromDate, range.toDate);
    return raw.map(mapRawComparisonToAdjustedPoint);
  }

  async getIndexHistory(name: string, range: DateRange): Promise<IndexBar[]> {
    const raw = await this.client.getIndexHistory(name, range.fromDate, range.toDate);
    return raw.map(mapRawIndexHistoryToBar);
  }
}

export const backendHistoricalDataProvider = new BackendHistoricalDataProvider();
