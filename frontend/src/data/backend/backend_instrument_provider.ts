import type { InstrumentProvider, ActiveInstrumentFilter } from "@/data/providers";
import type { CoveredWarrant } from "@/domain/models";
import { BackendClient, backendClient } from "./backend_client";
import { mapInstrumentToCoveredWarrant } from "./mappers";

export class BackendInstrumentProvider implements InstrumentProvider {
  private client: BackendClient;

  constructor(client?: BackendClient) {
    this.client = client || backendClient;
  }

  async getActiveCoveredWarrants(filter?: ActiveInstrumentFilter): Promise<CoveredWarrant[]> {
    const rawItems = await this.client.getActiveInstruments(filter?.issuer, filter?.underlyingSymbol);
    return rawItems.map(mapInstrumentToCoveredWarrant);
  }

  async getWarrantSpecification(symbol: string): Promise<CoveredWarrant | null> {
    try {
      const raw = await this.client.getInstrumentSpecification(symbol);
      if (raw) return mapInstrumentToCoveredWarrant(raw);
    } catch {
      // Fallback to cache search
    }
    const items = await this.getActiveCoveredWarrants();
    const found = items.find((cw) => cw.symbol.toUpperCase() === symbol.toUpperCase());
    return found || null;
  }

  async getUnderlyingSymbols(): Promise<string[]> {
    const items = await this.getActiveCoveredWarrants();
    const symbols = new Set<string>();
    items.forEach((cw) => {
      if (cw.underlyingSymbol) symbols.add(cw.underlyingSymbol.toUpperCase());
    });
    return Array.from(symbols).sort();
  }
}

export const backendInstrumentProvider = new BackendInstrumentProvider();
