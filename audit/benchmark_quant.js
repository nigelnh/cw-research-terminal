/**
 * Benchmark script for Quant Engine (Black-Scholes & Greeks)
 * Measures: Black-Scholes Call Price, Central Difference Delta, Gamma, Vega, Theta, Full Greeks Suite
 * Workloads: 1, 10, 100, 300 instruments, realistic portfolio (1000 items)
 */

import { performance } from 'node:perf_hooks';

// Hart / Abramowitz-Stegun approximation for CND
function cnd(x) {
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

function ndf(x) {
  return (1.0 / Math.sqrt(2.0 * Math.PI)) * Math.exp(-0.5 * x * x);
}

function bsCallPrice(S, K, t, r, sigma) {
  if (t <= 0) return Math.max(0, S - K);
  const d1 = (Math.log(S / K) + (r + (sigma * sigma) / 2) * t) / (sigma * Math.sqrt(t));
  const d2 = d1 - sigma * Math.sqrt(t);
  return S * cnd(d1) - K * Math.exp(-r * t) * cnd(d2);
}

// Codebase Central Difference Greeks
function calculateNumericalGreeks(S, K, t, r, sigma, cvr, balance) {
  const ratioNum = cvr;
  const theo_prc = bsCallPrice(S, K, t, r, sigma) / ratioNum;
  
  // Delta
  const priceUp = bsCallPrice(S * 1.0001, K, t, r, sigma);
  const priceDown = bsCallPrice(S * 0.9999, K, t, r, sigma);
  const delta = (priceUp - priceDown) / (S * 0.0002);
  const delta_lots = delta * balance;
  const delta_cash = S * delta_lots;

  // Gamma
  const delta_up = (bsCallPrice(S * 1.0001 * 1.0001, K, t, r, sigma) - bsCallPrice(S * 1.0001 * 0.9999, K, t, r, sigma)) / (S * 1.0001 * 0.0002);
  const delta_down = (bsCallPrice(S * 0.9999 * 1.0001, K, t, r, sigma) - bsCallPrice(S * 0.9999 * 0.9999, K, t, r, sigma)) / (S * 0.9999 * 0.0002);
  const gamma = (delta_up - delta_down) / (S * 0.0002);
  const gamma_amt_pct = gamma * 0.01 * S * balance;

  // Vega
  const priceVolUp = bsCallPrice(S, K, t, r, sigma + 0.0001) / ratioNum;
  const priceVolDown = bsCallPrice(S, K, t, r, sigma - 0.0001) / ratioNum;
  const vega_pct = (priceVolUp - priceVolDown) / 0.02;
  const cash_vega = vega_pct * balance;

  // Theta
  const newT = Math.max(t - 1 / 365, 0.0001);
  const priceNewT = bsCallPrice(S, K, newT, r, sigma) / ratioNum;
  const theta = priceNewT - theo_prc;
  const cash_theta = theta * balance;

  return { theo_prc, delta, delta_lots, delta_cash, gamma, gamma_amt_pct, vega_pct, cash_vega, theta, cash_theta };
}

// Analytical Closed-form Greeks for comparison
function calculateAnalyticalGreeks(S, K, t, r, sigma, cvr, balance) {
  if (t <= 0) return { theo_prc: Math.max(0, S - K) / cvr, delta: 0, gamma: 0, vega_pct: 0, theta: 0 };
  const d1 = (Math.log(S / K) + (r + (sigma * sigma) / 2) * t) / (sigma * Math.sqrt(t));
  const d2 = d1 - sigma * Math.sqrt(t);
  const callPrice = S * cnd(d1) - K * Math.exp(-r * t) * cnd(d2);
  const theo_prc = callPrice / cvr;
  const delta = cnd(d1);
  const gamma = ndf(d1) / (S * sigma * Math.sqrt(t));
  const vega = S * Math.sqrt(t) * ndf(d1);
  const vega_pct = (vega * 0.01) / cvr;
  const thetaYearly = -(S * ndf(d1) * sigma) / (2 * Math.sqrt(t)) - r * K * Math.exp(-r * t) * cnd(d2);
  const theta = (thetaYearly / 365) / cvr;
  return { theo_prc, delta, gamma, vega_pct, theta };
}

function runStats(latenciesNs) {
  latenciesNs.sort((a, b) => a - b);
  const n = latenciesNs.length;
  const mean = latenciesNs.reduce((a, b) => a + b, 0) / n;
  const median = latenciesNs[Math.floor(n * 0.5)];
  const p95 = latenciesNs[Math.floor(n * 0.95)];
  const p99 = latenciesNs[Math.floor(n * 0.99)];
  const min = latenciesNs[0];
  const max = latenciesNs[n - 1];
  return { min, mean, median, p95, p99, max };
}

function benchmarkSingleOperations(iterations = 100000) {
  console.log(`=== 1. SINGLE OPERATION BENCHMARK (${iterations.toLocaleString()} iterations, 10,000 warm-up) ===`);
  const S = 24150, K = 25000, t = 162 / 365, r = 0.0725, sigma = 0.325, cvr = 4, balance = 100000;

  // Warm up
  for (let i = 0; i < 10000; i++) {
    bsCallPrice(S, K, t, r, sigma);
    calculateNumericalGreeks(S, K, t, r, sigma, cvr, balance);
    calculateAnalyticalGreeks(S, K, t, r, sigma, cvr, balance);
  }

  // 1. Black-Scholes Call Price
  const bsTimes = [];
  for (let i = 0; i < iterations; i++) {
    const t0 = performance.now();
    bsCallPrice(S, K, t, r, sigma);
    const t1 = performance.now();
    bsTimes.push((t1 - t0) * 1000000); // ns
  }
  const bsStats = runStats(bsTimes);
  console.log(`BS Call Price:       Mean: ${bsStats.mean.toFixed(2)} ns | Median: ${bsStats.median.toFixed(2)} ns | P95: ${bsStats.p95.toFixed(2)} ns | P99: ${bsStats.p99.toFixed(2)} ns`);

  // 2. Full Numerical Greeks Suite (Codebase implementation)
  const numTimes = [];
  for (let i = 0; i < iterations; i++) {
    const t0 = performance.now();
    calculateNumericalGreeks(S, K, t, r, sigma, cvr, balance);
    const t1 = performance.now();
    numTimes.push((t1 - t0) * 1000000); // ns
  }
  const numStats = runStats(numTimes);
  console.log(`Numerical Greeks:    Mean: ${numStats.mean.toFixed(2)} ns | Median: ${numStats.median.toFixed(2)} ns | P95: ${numStats.p95.toFixed(2)} ns | P99: ${numStats.p99.toFixed(2)} ns`);

  // 3. Analytical Greeks Suite
  const anaTimes = [];
  for (let i = 0; i < iterations; i++) {
    const t0 = performance.now();
    calculateAnalyticalGreeks(S, K, t, r, sigma, cvr, balance);
    const t1 = performance.now();
    anaTimes.push((t1 - t0) * 1000000); // ns
  }
  const anaStats = runStats(anaTimes);
  console.log(`Analytical Greeks:   Mean: ${anaStats.mean.toFixed(2)} ns | Median: ${anaStats.median.toFixed(2)} ns | P95: ${anaStats.p95.toFixed(2)} ns | P99: ${anaStats.p99.toFixed(2)} ns`);

  const throughputNum = 1000000000 / numStats.mean;
  const throughputAna = 1000000000 / anaStats.mean;
  console.log(`\nThroughput (Single Core):`);
  console.log(`- Numerical Greeks:  ${Math.round(throughputNum).toLocaleString()} ops/sec`);
  console.log(`- Analytical Greeks: ${Math.round(throughputAna).toLocaleString()} ops/sec`);
}

function benchmarkBatchSizes(batches = [1, 10, 50, 100, 300, 1000], iterations = 5000) {
  console.log(`\n=== 2. BATCH REVALUATION BENCHMARK (${iterations.toLocaleString()} iterations per batch size) ===`);
  
  for (const size of batches) {
    // Generate synthetic portfolio
    const portfolio = [];
    for (let i = 0; i < size; i++) {
      portfolio.push({
        S: 20000 + (i % 50) * 1000,
        K: 21000 + (i % 30) * 1000,
        t: (30 + (i % 200)) / 365,
        r: 0.0725,
        sigma: 0.25 + (i % 20) * 0.01,
        cvr: 2 + (i % 4),
        balance: 10000 * (i + 1)
      });
    }

    // Warm up
    for (let i = 0; i < 500; i++) {
      for (let j = 0; j < size; j++) {
        const item = portfolio[j];
        calculateNumericalGreeks(item.S, item.K, item.t, item.r, item.sigma, item.cvr, item.balance);
      }
    }

    const batchTimes = [];
    for (let it = 0; it < iterations; it++) {
      const t0 = performance.now();
      for (let j = 0; j < size; j++) {
        const item = portfolio[j];
        calculateNumericalGreeks(item.S, item.K, item.t, item.r, item.sigma, item.cvr, item.balance);
      }
      const t1 = performance.now();
      batchTimes.push((t1 - t0) * 1000); // us
    }

    const stats = runStats(batchTimes);
    const perInstrumentUs = stats.mean / size;
    console.log(`Batch [${size.toString().padStart(4)}] Instruments: Mean: ${stats.mean.toFixed(2)} µs | Median: ${stats.median.toFixed(2)} µs | P95: ${stats.p95.toFixed(2)} µs | P99: ${stats.p99.toFixed(2)} µs | Per-item: ${perInstrumentUs.toFixed(3)} µs`);
  }
}

benchmarkSingleOperations();
benchmarkBatchSizes();
