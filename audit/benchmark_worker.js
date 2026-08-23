/**
 * Benchmark script for Frontend Web Worker operations:
 * State merging, tick direction propagation, and patch buffering.
 */

import { performance } from 'node:perf_hooks';

function benchmarkWorkerProcessing(iterations = 100000) {
  console.log(`=== 3. WEB WORKER STATE MERGING BENCHMARK (${iterations.toLocaleString()} iterations) ===`);

  const rowsMap = new Map();
  const pendingDirections = new Map();

  // Populate 300 active rows in worker memory
  for (let i = 0; i < 300; i++) {
    const sym = `CW_${i}`;
    rowsMap.set(sym, {
      Symbol: sym,
      Bid1_Prc: 3000 + i * 10,
      Bid1_Qty: 50000,
      Ask1_Prc: 3010 + i * 10,
      Ask1_Qty: 40000,
      Traded: 3005 + i * 10,
      Traded_Qty: 10000,
      _ts: Date.now()
    });
  }

  function propagateDirection(sym, key, dir) {
    pendingDirections.set(`${sym}:${key}`, dir);
    if (key === "Bid1_Prc") {
      pendingDirections.set(`${sym}:Bid1_Qty`, dir);
    } else if (key === "Ask1_Prc") {
      pendingDirections.set(`${sym}:Ask1_Qty`, dir);
    } else if (key === "Traded") {
      pendingDirections.set(`${sym}:Traded_Qty`, dir);
      pendingDirections.set(`${sym}:Change`, dir);
      pendingDirections.set(`${sym}:ChangePercent`, dir);
    }
  }

  function handlePatch(symbol, patch, ts) {
    const row = rowsMap.get(symbol) || { Symbol: symbol };
    const updatedRow = { ...row, ...patch, _ts: ts || Date.now() };
    rowsMap.set(symbol, updatedRow);

    for (const key in patch) {
      const newVal = patch[key];
      if (typeof newVal === 'number') {
        const oldVal = row[key];
        if (oldVal !== undefined && oldVal !== null && newVal !== oldVal) {
          propagateDirection(symbol, key, newVal > oldVal ? "up" : "down");
        }
      }
    }
    return updatedRow;
  }

  // Warm up
  for (let i = 0; i < 10000; i++) {
    const sym = `CW_${i % 300}`;
    handlePatch(sym, { Traded: 3010, Traded_Qty: 20000 }, Date.now());
  }

  const times = [];
  for (let i = 0; i < iterations; i++) {
    const sym = `CW_${i % 300}`;
    const t0 = performance.now();
    handlePatch(sym, { Traded: 3010 + (i % 5), Traded_Qty: 20000 + i }, Date.now());
    const t1 = performance.now();
    times.push((t1 - t0) * 1000); // us
  }

  times.sort((a, b) => a - b);
  const mean = times.reduce((a, b) => a + b, 0) / times.length;
  const median = times[Math.floor(times.length * 0.5)];
  const p95 = times[Math.floor(times.length * 0.95)];
  const p99 = times[Math.floor(times.length * 0.99)];

  console.log(`Worker Patch Merge + Direction Propagation: Mean: ${mean.toFixed(3)} µs | Median: ${median.toFixed(3)} µs | P95: ${p95.toFixed(3)} µs | P99: ${p99.toFixed(3)} µs`);
  console.log(`Worker Ingestion Throughput: ${Math.round(1000000 / mean).toLocaleString()} patches/sec`);
}

benchmarkWorkerProcessing();
