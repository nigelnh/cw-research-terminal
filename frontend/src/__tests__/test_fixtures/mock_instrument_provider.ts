import type { InstrumentProvider, ActiveInstrumentFilter } from "@/data/providers";
import type { CoveredWarrant } from "@/domain/models";
import initialSnapshots from "./market_snapshots.json";

export class MockInstrumentProvider implements InstrumentProvider {
  async getActiveCoveredWarrants(filter?: ActiveInstrumentFilter): Promise<CoveredWarrant[]> {
    let items = initialSnapshots as CoveredWarrant[];

    if (filter?.issuer) {
      items = items.filter((cw) => cw.issuer?.toLowerCase() === filter.issuer?.toLowerCase());
    }
    if (filter?.underlyingSymbol) {
      items = items.filter((cw) => cw.underlyingSymbol.toUpperCase() === filter.underlyingSymbol?.toUpperCase());
    }

    return items;
  }

  async getWarrantSpecification(symbol: string): Promise<CoveredWarrant | null> {
    const items = await this.getActiveCoveredWarrants();
    const found = items.find((cw) => cw.symbol.toUpperCase() === symbol.toUpperCase());
    return found || null;
  }

  async getUnderlyingSymbols(): Promise<string[]> {
    const items = await this.getActiveCoveredWarrants();
    const set = new Set<string>();
    items.forEach((cw) => set.add(cw.underlyingSymbol));
    return Array.from(set).sort();
  }
}

export const mockInstrumentProvider = new MockInstrumentProvider();
