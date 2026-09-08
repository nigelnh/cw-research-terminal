import type { MarketQuote } from "@/domain/models";

export function normalizeAnalytics(raw: Record<string, any>): Record<string, any> {
  const g = raw.greeks ?? {};
  return {
    ...raw, sessionDate: raw.sessionDate ?? raw.session_date,
    calculatedAt: raw.calculatedAt ?? raw.calculated_at,
    inputProvenance: raw.inputProvenance ?? raw.input_provenance,
    modelInputs: raw.modelInputs ?? raw.model_inputs,
    isAvailable: raw.isAvailable ?? raw.is_available,
    termsVersion: raw.termsVersion ?? raw.terms_version,
    ivBid: Object.hasOwnProperty.call(raw, "ivBid") ? raw.ivBid : raw.iv_bid ?? null,
    ivAsk: Object.hasOwnProperty.call(raw, "ivAsk") ? raw.ivAsk : raw.iv_ask ?? null,
    ivTrade: Object.hasOwnProperty.call(raw, "ivTrade") ? raw.ivTrade : raw.iv_trade ?? null,
    ivMid: raw.ivMid ?? raw.iv_mid ?? null,
    moneynessRatio: raw.moneynessRatio ?? raw.moneyness ?? null,
    moneynessCategory: raw.moneynessCategory ?? raw.moneyness_category ?? null,
    theoreticalPrice: raw.theoreticalPrice ?? g.theoretical_price ?? null,
    historicalVolatility: raw.historicalVolatility ?? raw.historical_volatility ?? null,
    delta: raw.delta ?? g.delta ?? null, gamma: raw.gamma ?? g.gamma ?? null,
    theta: raw.theta ?? g.theta ?? null, vega: raw.vega ?? g.vega ?? null, rho: raw.rho ?? g.rho ?? null,
    dte: raw.dte ?? raw.model_inputs?.days_to_expiry ?? null,
    contractState: raw.contractState ?? raw.contract_state ?? null,
  };
}

/** A null result is authoritative, never permission to read an unqualified CW cache. */
export function resolveDashboardAnalytics(
  candidates: Array<Record<string, any> | null | undefined>, quote: MarketQuote,
  session: string | null | undefined, underlying?: MarketQuote,
): Record<string, any> | null {
  const eligible = candidates.filter(Boolean).map(a => normalizeAnalytics(a!))
    .filter(a => a.isAvailable !== false && a.sessionDate && (!session || a.sessionDate === session))
    .sort((a, b) => Date.parse(b.calculatedAt ?? "") - Date.parse(a.calculatedAt ?? ""));
  const a = eligible[0];
  if (!a || [quote.lastPrice, quote.bidPrice, quote.askPrice].every(v => v == null)) return null;
  const inputs = a.modelInputs;
  if (!inputs || !a.inputProvenance?.underlying || a.inputProvenance.underlying.sessionDate !== a.sessionDate) return null;
  if (underlying && (underlying.marketSessionDate !== a.sessionDate || underlying.lastPrice !== inputs.underlying_price)) return null;
  const result = { ...a };
  for (const [field, price, input, group] of [
    ["ivBid", quote.bidPrice, inputs.market_bid, "book"],
    ["ivAsk", quote.askPrice, inputs.market_ask, "book"],
    ["ivTrade", quote.lastPrice, inputs.market_last, "trade"],
  ] as const) {
    if (price == null || price !== input || a.inputProvenance?.[group]?.sessionDate !== a.sessionDate) result[field] = null;
  }
  if (result.ivBid == null || result.ivAsk == null || (quote.askPrice ?? 0) < (quote.bidPrice ?? 0)) result.ivMid = null;
  const volatilitySource = a.greeksVolatilitySource ?? a.greeks?.volatility_source;
  if ((volatilitySource === "IV_TRADE" && result.ivTrade == null) ||
      (volatilitySource === "IV_MID" && result.ivMid == null) ||
      (volatilitySource === "IV_BID" && result.ivBid == null) ||
      (volatilitySource === "IV_ASK" && result.ivAsk == null)) {
    for (const field of ["delta", "gamma", "theta", "vega", "rho"]) result[field] = null;
  }
  return result;
}
