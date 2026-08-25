import type { CoveredWarrant } from "@/domain/models";

export interface ActiveInstrumentFilter {
  issuer?: string;
  underlyingSymbol?: string;
}

export interface InstrumentProvider {
  getActiveCoveredWarrants(filter?: ActiveInstrumentFilter): Promise<CoveredWarrant[]>;
  getWarrantSpecification(symbol: string): Promise<CoveredWarrant | null>;
  getUnderlyingSymbols(): Promise<string[]>;
}
