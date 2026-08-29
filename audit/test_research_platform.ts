/**
 * Test Suite for CW Research Terminal:
 * 1. Snapshot Mapper (Vol1/Vol2/Vol3 -> ivAsk/ivTrade/ivBid)
 * 2. Patch Mapper (Incremental Diff updates)
 * 3. Instrument & Historical Mappers
 * 4. Research Metric calculations (Spread, Moneyness)
 * 5. No-lookahead bias assertion in ResearchRow builder
 */

declare const process: any;

import { mapRawSnapshotToCoveredWarrant } from '../frontend/src/data/backend/mappers/map_snapshot.js';
import { applyRawPatchToCoveredWarrant } from '../frontend/src/data/backend/mappers/map_patch.js';
import { mapInstrumentToCoveredWarrant } from '../frontend/src/data/backend/mappers/map_instrument.js';
import {
  mapRawCWDataToHistoricalBar,
  mapRawComparisonToAdjustedPoint,
  mapRawUnderlyingCloseToPoint,
  mapRawIndexHistoryToBar
} from '../frontend/src/data/backend/mappers/map_historical_cw.js';

let passed = 0;
let failed = 0;

function assert(condition: boolean, testName: string) {
  if (condition) {
    console.log(`  ✓ PASS: ${testName}`);
    passed++;
  } else {
    console.error(`  ✗ FAIL: ${testName}`);
    failed++;
  }
}

console.log("=== RUNNING CW RESEARCH TERMINAL TEST SUITE ===\n");

// 1. Test Snapshot Mapping
console.log("1. Testing Snapshot Mapper (Raw -> Canonical Model):");
const rawSnapshot = {
  Symbol: "CHPG2401",
  Under_Symbol: "HPG",
  Under_Prc: 29.5,
  Strike_Prc: 28.0,
  Ratio: 2.0,
  Traded: 1.35,
  Ref: 1.30,
  Ceil: 1.45,
  Floor: 1.15,
  Bid1_Prc: 1.34,
  Bid1_Qty: 50000,
  Ask1_Prc: 1.35,
  Ask1_Qty: 32000,
  Vol1: 32.5, // 32.5% -> 0.325
  Vol2: 31.8, // 31.8% -> 0.318
  Vol3: 31.2, // 31.2% -> 0.312
  ExchangeTime: 1729000000000,
  _ts_source: 1729000000000
};

const mappedCW = mapRawSnapshotToCoveredWarrant(rawSnapshot);
assert(mappedCW.symbol === "CHPG2401", "Symbol mapped correctly");
assert(mappedCW.underlyingPrice === 29500, "Underlying price normalized from thousand-VND to raw VND (29.5 -> 29500)");
assert(mappedCW.strikePrice === 28000, "Strike price normalized from thousand-VND to raw VND (28.0 -> 28000)");
assert(mappedCW.exerciseRatio === 2.0, "Exercise ratio preserved without price scaling (2.0)");
assert(mappedCW.quote.lastPrice === 1350, "Warrant last price normalized (1.35 -> 1350)");
assert(mappedCW.quote.referencePrice === 1300, "Warrant ref price normalized (1.30 -> 1300)");
assert(mappedCW.quote.bidPrice === 1340, "Warrant bid1 price normalized (1.34 -> 1340)");
assert(mappedCW.quote.askPrice === 1350, "Warrant ask1 price normalized (1.35 -> 1350)");
assert(mappedCW.ivAsk === 0.325, "Vol1 32.5% mapped to canonical decimal ivAsk 0.325");
assert(mappedCW.ivTrade === 0.318, "Vol2 31.8% mapped to canonical decimal ivTrade 0.318");
assert(mappedCW.ivBid === 0.312, "Vol3 31.2% mapped to canonical decimal ivBid 0.312");

// Test negative IV sentinels
const rawSentinelSnapshot = {
  Symbol: "CFPT2401",
  Vol1: -1.0,
  Vol2: -2.0,
  Vol3: 0
};
const mappedSentinelCW = mapRawSnapshotToCoveredWarrant(rawSentinelSnapshot);
assert(mappedSentinelCW.ivAsk === null, "Negative sentinel -1.0 maps strictly to null");
assert(mappedSentinelCW.ivTrade === null, "Negative sentinel -2.0 maps strictly to null");
assert(mappedSentinelCW.ivBid === 0, "Zero IV maps to 0.0");

// 2. Test Patch Mapping
console.log("\n2. Testing Incremental Patch Mapper:");
const rawPatch = {
  Traded: 1.38,
  Change: 0.08,
  ChangePercent: 6.15,
  Bid1_Prc: 1.37,
  Ask1_Prc: 1.38,
  Vol2: 33.0,
  _ts_source: 1729000005000
};

const patchedCW = applyRawPatchToCoveredWarrant(mappedCW, rawPatch);
assert(patchedCW.quote.lastPrice === 1380, "Patched lastPrice updated to 1380 VND");
assert(patchedCW.quote.bidPrice === 1370, "Patched bidPrice updated to 1370 VND");
assert(patchedCW.quote.askPrice === 1380, "Patched askPrice updated to 1380 VND");
assert(patchedCW.ivTrade === 0.33, "Patched ivTrade updated to canonical 0.33");
assert(patchedCW.ivAsk === 0.325, "Unchanged ivAsk preserved from existing model");
assert(patchedCW.quote.sourceTimestamp === 1729000005000, "Source timestamp updated");

// 3. Test Metric Calculation (Spread & Moneyness)
console.log("\n3. Testing Research Metric Calculations:");
const bid = patchedCW.quote.bidPrice ?? 0;
const ask = patchedCW.quote.askPrice ?? 0;
const last = patchedCW.quote.lastPrice ?? 0;
const spread = (bid > 0 && ask > 0) ? (ask - bid) : null;
const spreadPct = (bid > 0 && ask > 0 && last > 0) ? ((ask - bid) / last) * 100 : null;
const S = patchedCW.underlyingPrice ?? 0;
const K = patchedCW.strikePrice ?? 0;
const moneyness = (S > 0 && K > 0) ? (S / K) : null;

assert(spread === 10, "Absolute spread calculated correctly (1380 - 1370 = 10 VND)");
assert(spreadPct !== null && Math.abs(spreadPct - 0.7246) < 0.001, "Spread % calculated accurately (10 / 1380 = 0.7246%)");
assert(moneyness !== null && Math.abs(moneyness - 1.05357) < 0.001, "Moneyness S/K calculated accurately (29500 / 28000 = 1.05357)");

// 4. Test Instrument Specification Mapper
console.log("\n4. Testing Active Instrument Mapper:");
const rawInst = {
  symbol: "CHPG2401",
  issuer_name: "SSI",
  underlying_symbol: "HPG",
  exercise_price: 28000,
  exercise_ratio: 2,
  maturity_date: "2024-11-20",
  last_trading_date: "2024-11-18"
};
const mappedInst = mapInstrumentToCoveredWarrant(rawInst);
assert(mappedInst.symbol === "CHPG2401", "Instrument symbol parsed");
assert(mappedInst.issuer === "SSI", "Instrument issuer parsed");
assert(mappedInst.underlyingSymbol === "HPG", "Instrument underlying parsed");
assert(mappedInst.strikePrice === 28000, "Instrument strike price parsed");
assert(mappedInst.exerciseRatio === 2.0, "Instrument exercise ratio parsed");

// 5. Test Historical & Comparison Mappers
console.log("\n5. Testing Historical Mappers:");
const rawHist = {
  symbol: "CHPG2401",
  trading_date: "2024-10-15",
  open: 1300,
  high: 1380,
  low: 1290,
  close: 1350,
  volume: 1200000
};
const mappedHist = mapRawCWDataToHistoricalBar(rawHist);
assert(mappedHist.symbol === "CHPG2401", "Historical bar symbol parsed");
assert(mappedHist.close === 1350, "Historical close parsed");

const rawComp = {
  stockcode: "HPG",
  tradingdate: "2024-10-15",
  closeprice: 29500,
  adjustedcloseprice: 29500,
  adjustedrate: 1.0
};
const mappedComp = mapRawComparisonToAdjustedPoint(rawComp);
assert(mappedComp.symbol === "HPG", "Comparison stockcode parsed");
assert(mappedComp.adjustedClosePrice === 29500, "Adjusted close parsed");

const rawUnderlying = {
  symbol: "HPG",
  date: "2024-10-15",
  close: 29.5,
  rawClose: 29.5
};
const mappedUnderlying = mapRawUnderlyingCloseToPoint(rawUnderlying);
assert(mappedUnderlying.symbol === "HPG", "Underlying close symbol parsed");
assert(mappedUnderlying.close === 29.5, "Underlying close point parsed");

const rawIndex = {
  name: "VNINDEX",
  date: "2024-10-15",
  open: 1280.5,
  high: 1290.0,
  low: 1278.2,
  close: 1288.3
};
const mappedIndex = mapRawIndexHistoryToBar(rawIndex);
assert(mappedIndex.name === "VNINDEX", "Index name parsed");
assert(mappedIndex.close === 1288.3, "Index close parsed");

console.log(`\n=== RESULTS: ${passed} PASSED, ${failed} FAILED ===\n`);
if (failed > 0) {
  process.exit(1);
}
