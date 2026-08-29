import type { CoveredWarrant } from "@/domain/models";

export interface ActiveInstrumentFilter {
  issuer?: string;
  underlyingSymbol?: string;
  /** "ALL" browses the whole discovered registry (research tab); default is active-only. */
  status?: "ACTIVE" | "ALL";
}

export interface InstrumentProvider {
  getActiveCoveredWarrants(filter?: ActiveInstrumentFilter): Promise<CoveredWarrant[]>;
  getWarrantSpecification(symbol: string): Promise<CoveredWarrant | null>;
  getUnderlyingSymbols(): Promise<string[]>;
}
