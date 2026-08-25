import { describe, it, expect } from "vitest";

// Standard Normal CDF approximation (Hart / Abramowitz-Stegun)
function cnd(x: number): number {
  const a1 = 0.319381530;
  const a2 = -0.356563782;
  const a3 = 1.781477937;
  const a4 = -1.821255978;
  const a5 = 1.330274429;
  const L = Math.abs(x);
  const K = 1.0 / (1.0 + 0.2316419 * L);
  let w = 1.0 - 1.0 / Math.sqrt(2.0 * Math.PI) * Math.exp(-L * L / 2.0) * (a1 * K + a2 * K * K + a3 * Math.pow(K, 3) + a4 * Math.pow(K, 4) + a5 * Math.pow(K, 5));
  if (x < 0) {
    w = 1.0 - w;
  }
  return w;
}

function ndf(x: number): number {
  return (1.0 / Math.sqrt(2.0 * Math.PI)) * Math.exp(-0.5 * x * x);
}

export function calculateAnalyticalGreeks(
  S: number,
  K: number,
  T: number,
  r: number,
  sigma: number,
  k: number
) {
  if (S <= 0 || K <= 0 || k <= 0) {
    return { theoreticalPrice: 0, delta: 0, gamma: 0, thetaDaily: 0, vega1Pct: 0 };
  }
  if (T <= 0) {
    return {
      theoreticalPrice: Math.max(0, S - K) / k,
      delta: S > K ? 1 / k : 0,
      gamma: 0,
      thetaDaily: 0,
      vega1Pct: 0,
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
  
  // Theta per calendar day (1/365 year)
  const thetaYearly = -(S * ndf(d1) * clampedSigma) / (2 * sqrtT) - r * K * Math.exp(-r * T) * cnd(d2);
  const thetaDaily = thetaYearly / (365 * k);

  // Vega per 1 percentage point (0.01) volatility change
  const vegaUnit = S * sqrtT * ndf(d1) / k;
  const vega1Pct = vegaUnit * 0.01;

  return { theoreticalPrice, delta, gamma, thetaDaily, vega1Pct };
}

describe("Quantitative Golden Vectors & Edge Cases", () => {
  it("Vector 1 (Standard Base Case): S=29500, K=28000, T=0.42, r=0.065, sigma=0.35, k=2.0", () => {
    const res = calculateAnalyticalGreeks(29500, 28000, 0.42, 0.065, 0.35, 2.0);

    // Verified analytical limits:
    expect(res.theoreticalPrice).toBeGreaterThan(1800);
    expect(res.theoreticalPrice).toBeLessThan(2300);
    expect(res.delta).toBeGreaterThan(0.30); // delta <= 1/k = 0.50
    expect(res.delta).toBeLessThan(0.45);
    expect(res.gamma).toBeGreaterThan(0);
    expect(res.thetaDaily).toBeLessThan(0); // Time decay is negative
    expect(res.vega1Pct).toBeGreaterThan(0);
  });

  it("Vector 2 (At-The-Money ATM): S=30000, K=30000, T=0.25, r=0.05, sigma=0.30, k=1.0", () => {
    const res = calculateAnalyticalGreeks(30000, 30000, 0.25, 0.05, 0.30, 1.0);

    // ATM Call Delta should be approximately 0.50 ~ 0.55
    expect(res.delta).toBeGreaterThan(0.50);
    expect(res.delta).toBeLessThan(0.60);
    expect(res.theoreticalPrice).toBeGreaterThan(1500);
    expect(res.gamma).toBeGreaterThan(0);
    expect(res.thetaDaily).toBeLessThan(0);
  });

  it("Vector 3 (Deep In-The-Money ITM): S=50000, K=20000, T=0.5, r=0.05, sigma=0.25, k=2.0", () => {
    const res = calculateAnalyticalGreeks(50000, 20000, 0.5, 0.05, 0.25, 2.0);

    // For deep ITM, Delta -> 1/k = 0.50, Gamma -> 0, Vega -> 0
    expect(res.delta).toBeCloseTo(0.50, 2);
    expect(res.gamma).toBeCloseTo(0, 4);
    expect(res.vega1Pct).toBeCloseTo(0, 1);
    // Price close to (S - K * e^-rT) / k
    const expectedFloor = (50000 - 20000 * Math.exp(-0.05 * 0.5)) / 2.0;
    expect(res.theoreticalPrice).toBeCloseTo(expectedFloor, 0);
  });

  it("Vector 4 (Deep Out-of-The-Money OTM): S=15000, K=40000, T=0.2, r=0.05, sigma=0.30, k=1.0", () => {
    const res = calculateAnalyticalGreeks(15000, 40000, 0.2, 0.05, 0.30, 1.0);

    // For deep OTM, Price -> 0, Delta -> 0, Gamma -> 0
    expect(res.theoreticalPrice).toBeCloseTo(0, 2);
    expect(res.delta).toBeCloseTo(0, 3);
    expect(res.gamma).toBeCloseTo(0, 4);
  });

  it("Vector 5 (Near Expiration T -> 0): S=30500, K=30000, T=1/365, r=0.05, sigma=0.30, k=1.0", () => {
    const res = calculateAnalyticalGreeks(30500, 30000, 1 / 365, 0.05, 0.30, 1.0);

    // ITM at expiration -> Price approaches intrinsic value 500 VND
    expect(res.theoreticalPrice).toBeGreaterThan(490);
    expect(res.theoreticalPrice).toBeLessThan(550);
    expect(res.delta).toBeGreaterThan(0.80);
  });

  it("Vector 6 (Expired T <= 0): S=32000, K=30000, T=0, r=0.05, sigma=0.30, k=2.0", () => {
    const res = calculateAnalyticalGreeks(32000, 30000, 0, 0.05, 0.30, 2.0);

    expect(res.theoreticalPrice).toBe(1000); // (32000 - 30000) / 2
    expect(res.delta).toBe(0.5);             // 1/k
    expect(res.gamma).toBe(0);
    expect(res.thetaDaily).toBe(0);
    expect(res.vega1Pct).toBe(0);
  });

  it("Vector 7 (Invalid / Boundary Inputs): S <= 0 or k <= 0", () => {
    const resZeroSpot = calculateAnalyticalGreeks(0, 30000, 0.5, 0.05, 0.30, 1.0);
    expect(resZeroSpot.theoreticalPrice).toBe(0);

    const resZeroRatio = calculateAnalyticalGreeks(30000, 30000, 0.5, 0.05, 0.30, 0);
    expect(resZeroRatio.theoreticalPrice).toBe(0);
  });
});
