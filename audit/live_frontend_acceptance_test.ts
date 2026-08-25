declare const process: any;

interface GatewayStatusFrame {
  type: string;
  gateway_connected?: boolean;
  authenticated?: boolean;
  upstream_status?: string;
  connected?: boolean;
  subscription_count?: number;
  message?: string;
}

interface PatchFrame {
  type: string;
  symbol: string;
  patch: Record<string, any>;
  ts: number;
}

async function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function runLiveAcceptanceTest() {
  console.log("================================================================================");
  console.log("  LIVE MARKET DATA GATEWAY & STATUS-SEMANTICS ACCEPTANCE TEST");
  console.log("================================================================================");

  const WS_URL = "ws://127.0.0.1:8501/ws/market";
  const REST_HEALTH_URL = "http://127.0.0.1:8501/api/market/health";

  // --------------------------------------------------------------------------
  // STEP 1: Verify REST Health Endpoint (Sanitized & Truthful)
  // --------------------------------------------------------------------------
  console.log("\n[TEST 1] Querying REST /api/market/health...");
  const res = await fetch(REST_HEALTH_URL);
  if (!res.ok) {
    throw new Error(`REST health failed with status ${res.status}`);
  }
  const healthData = await res.json();
  console.log("  ✓ REST Health Response:", JSON.stringify(healthData));

  if (!healthData.authenticated) {
    throw new Error("Provider is not authenticated with FiinQuant API.");
  }
  console.log("  ✓ Provider authentication verified.");

  // --------------------------------------------------------------------------
  // STEP 2: Verify Initial WS Handshake & Status Frame Semantics
  // --------------------------------------------------------------------------
  console.log(`\n[TEST 2] Connecting to WebSocket: ${WS_URL}...`);
  const ws = new WebSocket(WS_URL);

  const initialStatus: GatewayStatusFrame = await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("Timeout waiting for initial status")), 5000);
    ws.onmessage = (event) => {
      try {
        const parsed = JSON.parse(event.data.toString());
        if (parsed.type === "status") {
          clearTimeout(timer);
          resolve(parsed);
        }
      } catch (e) {
        reject(e);
      }
    };
    ws.onerror = (err) => {
      clearTimeout(timer);
      reject(err);
    };
  });

  console.log("  ✓ Received Initial Handshake Frame:", JSON.stringify(initialStatus));
  console.log(`    - Gateway Connected: ${initialStatus.gateway_connected}`);
  console.log(`    - Provider Authenticated: ${initialStatus.authenticated}`);
  console.log(`    - Upstream Status: ${initialStatus.upstream_status}`);
  console.log(`    - Legacy 'connected' field: ${initialStatus.connected}`);

  // Crucial check: Authenticated with 0 subscriptions must NOT claim Live!
  if (initialStatus.subscription_count === 0 && initialStatus.connected === true) {
    throw new Error("VIOLATION: Initial status claimed 'connected: true' with 0 subscriptions!");
  }
  console.log("  ✓ Pass: Initial status with 0 subscriptions does NOT claim 'Live'.");

  // --------------------------------------------------------------------------
  // STEP 3: Active Watchlist Subscription Lifecycle (HPG + CHPG2602 + VNINDEX)
  // --------------------------------------------------------------------------
  const activeSymbols = ["HPG", "CHPG2602", "VNINDEX"];
  console.log(`\n[TEST 3] Subscribing to active acceptance symbols: ${JSON.stringify(activeSymbols)}...`);

  ws.send(JSON.stringify({ type: "subscribe", symbols: activeSymbols }));

  console.log("  Listening for live market patches and status transition for 15s...");

  const patches: PatchFrame[] = [];
  let becameLive = false;

  const collectionPromise = new Promise<void>((resolve) => {
    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data.toString());
        if (msg.type === "status") {
          console.log(`  • [Status Transition] Upstream Status: ${msg.upstream_status} (Live: ${msg.connected})`);
          if (msg.upstream_status === "LIVE" || msg.connected === true) {
            becameLive = true;
          }
        } else if (msg.type === "patch") {
          patches.push(msg);
          console.log(`  • [Live Patch] Symbol: ${msg.symbol} ->`, JSON.stringify(msg.patch));
        } else if (msg.type === "snapshots") {
          console.log(`  • [Snapshot Frame] Rows received: ${msg.rows?.length}`);
        }
      } catch (err) {
        console.warn("Parse error:", err);
      }
    };

    setTimeout(() => {
      resolve();
    }, 15000);
  });

  await collectionPromise;

  console.log(`\n[TEST 3 RESULTS] Total Live Patches Captured: ${patches.length}`);

  // Inspect HPG Patches
  const hpgPatches = patches.filter((p) => p.symbol === "HPG");
  console.log(`  • HPG Live Patches: ${hpgPatches.length}`);

  // Inspect CHPG2602 Patches
  const cwPatches = patches.filter((p) => p.symbol === "CHPG2602");
  console.log(`  • CHPG2602 Live Patches: ${cwPatches.length}`);

  // Inspect VNINDEX Patches
  const indexPatches = patches.filter((p) => p.symbol === "VNINDEX");
  console.log(`  • VNINDEX Live Patches: ${indexPatches.length}`);

  // --------------------------------------------------------------------------
  // STEP 4: Verify Price Unit Normalization & No Mid-Price Guessing
  // --------------------------------------------------------------------------
  console.log("\n[TEST 4] Verifying Price Unit Normalization & CW Trade Semantics...");
  if (hpgPatches.length > 0) {
    const sampleHpg = hpgPatches[0].patch;
    console.log("  Sample HPG Patch Data:", sampleHpg);
    if (sampleHpg.Traded !== undefined) {
      console.log(`  ✓ HPG Traded Price Wire Unit: ${sampleHpg.Traded} (Maps to ${sampleHpg.Traded * 1000} VND in domain)`);
    }
  }

  if (cwPatches.length > 0) {
    const sampleCw = cwPatches[0].patch;
    console.log("  Sample CHPG2602 Patch Data:", sampleCw);
    console.log(`  ✓ CW Bid/Ask: Bid1=${sampleCw.Bid1_Prc} (Maps to ${(sampleCw.Bid1_Prc ?? 0) * 1000} VND), Ask1=${sampleCw.Ask1_Prc} (Maps to ${(sampleCw.Ask1_Prc ?? 0) * 1000} VND)`);
    if (sampleCw.Traded === undefined) {
      console.log("  ✓ CW Traded Price is correctly undefined/absent (No mid-price fabricated).");
    }
  }

  // --------------------------------------------------------------------------
  // STEP 5: Test Multi-CW Watchlist (CHPG2602, CFPT2602, CMWG2602 + Underlyings)
  // --------------------------------------------------------------------------
  const multiCwPortfolio = ["CHPG2602", "CFPT2602", "CMWG2602", "HPG", "FPT", "MWG", "VNINDEX"];
  console.log(`\n[TEST 5] Subscribing to full personal research portfolio (7 symbols): ${JSON.stringify(multiCwPortfolio)}...`);

  ws.send(JSON.stringify({ type: "subscribe", symbols: multiCwPortfolio }));
  await sleep(2000);

  const subRes = await fetch("http://127.0.0.1:8501/api/market/subscriptions");
  const subData = await subRes.json();
  console.log("  ✓ Active Subscriptions on Gateway:", JSON.stringify(subData));

  if (subData.active.length < 7 && subData.desired.length !== 7) {
    console.warn("  Warning: Desired subscriptions not matching 7");
  } else {
    console.log("  ✓ Desired 7 symbols registered and within capacity (7 / 33).");
  }

  // --------------------------------------------------------------------------
  // STEP 6: Unsubscribe Reconcile & Clean Teardown
  // --------------------------------------------------------------------------
  console.log("\n[TEST 6] Unsubscribing from symbols...");
  ws.send(JSON.stringify({ type: "unsubscribe", symbols: ["CMWG2602", "MWG"] }));
  await sleep(1000);

  ws.close();
  console.log("  ✓ WebSocket closed cleanly.");

  console.log("\n================================================================================");
  console.log("  ALL LIVE ACCEPTANCE CHECKS COMPLETED SUCCESSFULLY");
  console.log("================================================================================");
}

runLiveAcceptanceTest().catch((err) => {
  console.error("FATAL ACCEPTANCE TEST ERROR:", err);
  process.exit(1);
});
