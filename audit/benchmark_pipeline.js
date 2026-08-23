/**
 * Benchmark script for Market Data Pipeline, Differential Patching Payload Reduction,
 * Serialization overhead, and Event Loop Latency under simulated tick storms.
 */

import { performance } from 'node:perf_hooks';

// 1. Measure Representative Snapshot vs Patch Payload Sizes
function benchmarkPayloadSizes() {
  console.log("=== 1. PAYLOAD COMPRESSION BENCHMARK (Snapshot vs Incremental Patch) ===");

  const fullSnapshot = {
    type: "snapshot",
    symbol: "CHPG2601",
    row: {
      Symbol: "CHPG2601",
      Ceil: 4500,
      Floor: 2100,
      Ref: 3000,
      Prior_Price: 3000,
      Bid1_Prc: 3050,
      Bid1_Qty: 50000,
      Bid2_Prc: 3040,
      Bid2_Qty: 30000,
      Bid3_Prc: 3030,
      Bid3_Qty: 25000,
      Ask1_Prc: 3060,
      Ask1_Qty: 40000,
      Ask2_Prc: 3070,
      Ask2_Qty: 20000,
      Ask3_Prc: 3080,
      Ask3_Qty: 15000,
      Traded: 3060,
      Traded_Qty: 10000,
      Change: 60,
      ChangePercent: 2.0,
      Total_Vol: 1250000,
      Total_Val: 3825000000,
      Avg_Prc: 3055,
      Open_Prc: 3010,
      High_Prc: 3090,
      Low_Prc: 3000,
      FB: 100000,
      FS: 50000,
      FR: 1500000,
      FO: 2000000,
      Total_Bid_Qty: 450000,
      Total_Offer_Qty: 380000,
      PT_Match_Prc: 0,
      PT_Match_Qty: 0,
      PT_Total_Qty: 0,
      PT_Total_Val: 0,
      Under_Symbol: "HPG",
      Exercise_Prc: 30000,
      Exercise_Ratio: 3,
      OpenInterest: "500000",
      OpenInterestChange: "+20000",
      FloorCode: "VN",
      Exchange: "HOSE",
      Status: "ACTIVE",
      ExchangeTime: 1718873400000,
      _ts_source: 1718873400015
    },
    ts: 1718873400020,
    ts_origin: 1718873400015
  };

  const typicalTradePatch = {
    type: "patch",
    symbol: "CHPG2601",
    patch: {
      Symbol: "CHPG2601",
      Traded: 3070,
      Traded_Qty: 15000,
      Change: 70,
      ChangePercent: 2.33,
      Total_Vol: 1265000,
      Total_Val: 3871050000
    },
    ts: 1718873400030,
    ts_origin: 1718873400025
  };

  const typicalQuotePatch = {
    type: "patch",
    symbol: "CHPG2601",
    patch: {
      Symbol: "CHPG2601",
      Bid1_Prc: 3060,
      Bid1_Qty: 55000
    },
    ts: 1718873400040,
    ts_origin: 1718873400035
  };

  const rawSnapshotJson = JSON.stringify(fullSnapshot);
  const rawTradePatchJson = JSON.stringify(typicalTradePatch);
  const rawQuotePatchJson = JSON.stringify(typicalQuotePatch);

  const snapshotBytes = Buffer.byteLength(rawSnapshotJson, 'utf8');
  const tradePatchBytes = Buffer.byteLength(rawTradePatchJson, 'utf8');
  const quotePatchBytes = Buffer.byteLength(rawQuotePatchJson, 'utf8');

  const tradeReduction = ((snapshotBytes - tradePatchBytes) / snapshotBytes) * 100;
  const quoteReduction = ((snapshotBytes - quotePatchBytes) / snapshotBytes) * 100;

  console.log(`Full Snapshot Payload:   ${snapshotBytes} bytes`);
  console.log(`Typical Trade Patch:     ${tradePatchBytes} bytes (Reduction: ${tradeReduction.toFixed(2)}%)`);
  console.log(`Typical Quote Patch:     ${quotePatchBytes} bytes (Reduction: ${quoteReduction.toFixed(2)}%)`);
  console.log(`Average Patch Payload:   ${Math.round((tradePatchBytes + quotePatchBytes) / 2)} bytes (Average Reduction: ${(((snapshotBytes - ((tradePatchBytes + quotePatchBytes) / 2)) / snapshotBytes) * 100).toFixed(2)}%)`);
}

// 2. Measure Ingestion, Diffing & Serialization Overhead
function benchmarkDiffingOverhead(iterations = 100000) {
  console.log(`\n=== 2. DIFF COMPUTATION & SERIALIZATION BENCHMARK (${iterations.toLocaleString()} iterations) ===`);

  const prevRow = {
    Symbol: "HPG", Ceil: 32000, Floor: 28000, Ref: 30000,
    Bid1_Prc: 30100, Bid1_Qty: 100000, Ask1_Prc: 30200, Ask1_Qty: 80000,
    Traded: 30150, Traded_Qty: 5000, Total_Vol: 15000000, Total_Val: 450000000000,
    Change: 150, ChangePercent: 0.5
  };

  const incomingRow = {
    Symbol: "HPG", Ceil: 32000, Floor: 28000, Ref: 30000,
    Bid1_Prc: 30100, Bid1_Qty: 105000, Ask1_Prc: 30200, Ask1_Qty: 80000,
    Traded: 30200, Traded_Qty: 10000, Total_Vol: 15010000, Total_Val: 450302000000,
    Change: 200, ChangePercent: 0.67
  };

  const sessionFields = [
    "Ask1_Qty", "Ask1_Prc", "Traded", "Traded_Qty", "Bid1_Prc", "Bid1_Qty",
    "Total_Vol", "Total_Val", "Change", "ChangePercent"
  ];

  // Warm up
  for (let i = 0; i < 10000; i++) {
    const patch = { Symbol: incomingRow.Symbol };
    for (const f of sessionFields) {
      if (incomingRow[f] !== prevRow[f]) patch[f] = incomingRow[f];
    }
    JSON.stringify({ type: "patch", symbol: "HPG", patch, ts: Date.now() });
  }

  const times = [];
  for (let i = 0; i < iterations; i++) {
    const t0 = performance.now();
    const patch = { Symbol: incomingRow.Symbol };
    let hasChanges = false;
    for (const f of sessionFields) {
      if (incomingRow[f] !== prevRow[f]) {
        patch[f] = incomingRow[f];
        hasChanges = true;
      }
    }
    if (hasChanges) {
      const payload = JSON.stringify({ type: "patch", symbol: "HPG", patch, ts: Date.now() });
    }
    const t1 = performance.now();
    times.push((t1 - t0) * 1000); // us
  }

  times.sort((a, b) => a - b);
  const mean = times.reduce((a, b) => a + b, 0) / times.length;
  const p95 = times[Math.floor(times.length * 0.95)];
  const p99 = times[Math.floor(times.length * 0.99)];

  console.log(`Diff + JSON Serialization Latency: Mean: ${mean.toFixed(3)} µs | P95: ${p95.toFixed(3)} µs | P99: ${p99.toFixed(3)} µs`);
  console.log(`Throughput: ${Math.round(1000000 / mean).toLocaleString()} messages/sec per core`);
}

benchmarkPayloadSizes();
benchmarkDiffingOverhead();
