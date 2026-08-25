import type { QuantProvider, PricingParams, PricingResult, DateRange } from "@/data/providers";
import type { HistoricalVolatilityPoint, BetaPoint } from "@/domain/models";
import volFixtures from "../fixtures/volatility_history.json";

function cnd(x: number): number {
  const a1 = 0.319381530;
  const a2 = -0.356563782;
  const a3 = 1.781477937;
  const a4 = -1.821255978;
  const a5 = 1.330274429;
  const L = Math.abs(x);
  const K = 1.0 / (1.0 + 0.2316419 * L);
  let w = 1.0 - 1.0 / Math.sqrt(2.0 * Math.PI) * Math.exp(-L * L / 2.0) * (a1 * K + a2 * K * K + a3 * Math.pow(K, 3) + a4 * Math.pow(K, 4) + a5 * Math.pow(K, 5));
  if (x < 0) w = 1.0 - w;
  return w;
}

function ndf(x: number): number {
  return (1.0 / Math.sqrt(2.0 * Math.PI)) * Math.exp(-0.5 * x * x);
}

/**
 * ============================================================================
 * DEMO / LOCAL MOCK QUANTITATIVE ANALYTICS PROVIDER
 * ============================================================================
 * NOTICE: This class provides deterministic Black-Scholes and Greek calculations
 * strictly for local UI/client development and testing without external services.
 * 
 * IT MUST NOT BE TREATED AS THE PRODUCTION QUANT ENGINE.
 * 
 * The authoritative production quantitative calculation engine is the
 * `cw_gui` Python quantitative service (FastAPI + Numba @njit JIT-accelerated
 * Black-Scholes solver and historical volatility time-series calculators).
 * ============================================================================
 */
export class MockQuantProvider implements QuantProvider {
  async calculateGreeks(params: PricingParams): Promise<PricingResult> {
    const { underlyingPrice: S, strikePrice: K, timeToMaturity: T, riskFreeRate: r, volatility: sigma, exerciseRatio: k } = params;

    // Strict boundary validation for invalid financial inputs
    if (S <= 0 || K <= 0 || k <= 0 || sigma < 0 || T < 0) {
      return {
        theoreticalPrice: null,
        delta: null,
        gamma: null,
        theta: null,
        vega: null,
        impliedVolatility: null,
      };
    }

    if (T === 0) {
      return {
        theoreticalPrice: Math.max(0, S - K) / k,
        delta: S > K ? 1 / k : (S < K ? 0 : 0.5 / k),
        gamma: 0,
        theta: 0,
        vega: 0,
        impliedVolatility: null,
      };
    }

    const clampedSigma = Math.max(1e-4, Math.min(sigma, 10.0));
    const sqrtT = Math.sqrt(T);
    const d1 = (Math.log(S / K) + (r + 0.5 * clampedSigma * clampedSigma) * T) / (clampedSigma * sqrtT);
    const d2 = d1 - clampedSigma * sqrtT;

    const bsCall = S * cnd(d1) - K * Math.exp(-r * T) * cnd(d2);
    const theoreticalPrice = Math.max(0, bsCall) / k;
    const delta = cnd(d1) / k;
    const gamma = ndf(d1) / (S * clampedSigma * sqrtT * k);
    const thetaYearly = -(S * ndf(d1) * clampedSigma) / (2 * sqrtT) - r * K * Math.exp(-r * T) * cnd(d2);
    const thetaDaily = thetaYearly / (365 * k);
    const vegaUnit = (S * sqrtT * ndf(d1)) / k;
    const vega1Pct = vegaUnit * 0.01;

    return {
      theoreticalPrice,
      delta,
      gamma,
      theta: thetaDaily,
      vega: vega1Pct,
      impliedVolatility: sigma,
    };
  }

  async getHistoricalVolatility(symbol: string, range?: DateRange): Promise<HistoricalVolatilityPoint[]> {
    const sym = symbol.toUpperCase();
    let data = (volFixtures as HistoricalVolatilityPoint[]).filter((v) => v.symbol === sym);
    if (range) {
      data = data.filter((v) => v.date >= range.fromDate && v.date <= range.toDate);
    }
    return data;
  }

  async getBeta(symbol: string, _range?: DateRange): Promise<BetaPoint[]> {
    const sym = symbol.toUpperCase();
    return [
      { symbol: sym, date: "2024-05-20", beta1m: 1.15, beta3m: 1.08, beta12m: 1.12 },
    ];
  }
}

export const mockQuantProvider = new MockQuantProvider();
