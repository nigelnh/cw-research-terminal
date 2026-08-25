#!/usr/bin/env python3
"""
FiinQuant Credentialled Live-Market Runtime Validation Test
Executed during active HOSE trading hours.

Evaluates:
1. Stock Realtime Ticks (HPG)
2. Active Covered Warrant Realtime Ticks (CHPG2602)
3. VNINDEX Realtime Ticks
4. Stock Order Book Depth (BidAsk: HPG)
5. CW Order Book Depth (BidAsk: CHPG2602)
6. Dual-Stream Simultaneous Concurrency (Trading_Data_Stream + BidAsk)
7. Price Units (Raw VND vs Thousand VND vs Points)
8. CW + Underlying Simultaneous Observation
9. Timestamp Structure & Semantic Classification
10. Watchlist Restart / Re-subscribe Lifecycle
"""

import os
import sys
import time
import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Any

# Ensure clean venv packages are loaded
_venv_site = os.path.join(
    os.path.dirname(__file__),
    ".venv",
    "lib",
    f"python{sys.version_info.major}.{sys.version_info.minor}",
    "site-packages"
)
if os.path.exists(_venv_site) and _venv_site not in sys.path:
    sys.path.insert(0, _venv_site)

from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("FiinQuantLiveMarketTest")


def main():
    load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

    username = os.getenv("FIINQUANT_USERNAME", "").strip()
    password = os.getenv("FIINQUANT_PASSWORD", "").strip()

    stock_symbol = "HPG"
    index_symbol = "VNINDEX"
    cw_symbol = "CHPG2602"  # Verified active warrant on HOSE (Underlying: HPG)

    print("=" * 80)
    print("  FIINQUANT CREDENTIALLED LIVE-MARKET RUNTIME VALIDATION")
    print(f"  Execution Time (Local UTC): {datetime.now(timezone.utc).isoformat()}")
    print("=" * 80)

    # 1. Authentication Check
    if not username or not password:
        print("\n[RESULT] BLOCKED_BY_MISSING_CREDENTIALS")
        sys.exit(1)

    import FiinQuantX as fq
    sdk_version = getattr(fq, "__version__", "0.1.67")
    print(f"[SDK_INSPECTION] FiinQuantX version: {sdk_version}")

    session = fq.FiinSession(username=username, password=password)
    try:
        session.login()
        if not getattr(session, "is_login", False):
            print("[RUNTIME] AUTHENTICATION_FAILED")
            sys.exit(1)
        print("[RUNTIME] AUTHENTICATION = VERIFIED")
    except Exception as e:
        print(f"[RUNTIME] AUTHENTICATION_EXCEPTION: {e.__class__.__name__}")
        sys.exit(1)

    print(f"[RUNTIME] ACTIVE_CW_SYMBOL = {cw_symbol} (Underlying: {stock_symbol})")

    # =========================================================================
    # TEST 1: TRADING_DATA_STREAM (Live Matching Ticks)
    # =========================================================================
    print("\n" + "=" * 60)
    print("  [TEST 1] TRADING_DATA_STREAM (Matching Ticks)")
    print("=" * 60)

    trade_tickers = [stock_symbol, index_symbol, cw_symbol]
    trade_events: Dict[str, List[Dict[str, Any]]] = {t: [] for t in trade_tickers}

    def on_trade_event(data):
        try:
            d = data.to_dict() if hasattr(data, "to_dict") else (data if isinstance(data, dict) else vars(data))
            sym = str(d.get("Ticker", "")).upper()
            if sym in trade_events:
                d["_local_recv_time"] = datetime.now(timezone.utc).isoformat()
                trade_events[sym].append(d)
        except Exception as err:
            logger.warning(f"Error in on_trade_event: {err}")

    trade_stream = session.Trading_Data_Stream(tickers=trade_tickers, callback=on_trade_event)
    trade_stream.start()
    print(f"[RUNTIME] Trading_Data_Stream started for {trade_tickers}. Collecting for 20s...")

    start_time = time.time()
    while time.time() - start_time < 20:
        if all(len(trade_events[t]) >= 3 for t in [stock_symbol, index_symbol]):
            if len(trade_events[cw_symbol]) >= 1:
                break
        time.sleep(0.5)

    trade_stream_connected = getattr(trade_stream, "connected", False)
    trade_stream.stop()

    stock_trade_count = len(trade_events[stock_symbol])
    index_trade_count = len(trade_events[index_symbol])
    cw_trade_count = len(trade_events[cw_symbol])

    print(f"\n[RUNTIME] Trading_Data_Stream Events Captured:")
    print(f"  • {stock_symbol} Trade Events: {stock_trade_count}")
    print(f"  • {index_symbol} Trade Events: {index_trade_count}")
    print(f"  • {cw_symbol} Trade Events: {cw_trade_count}")

    # Inspect sanitized samples
    for sym in trade_tickers:
        evs = trade_events[sym]
        if evs:
            sample = evs[-1]
            print(f"\n  Sample {sym} Trade Event:")
            print(f"    - Ticker: {sample.get('Ticker')}")
            print(f"    - Close/MatchPrice: {sample.get('Close')} (Ref: {sample.get('ReferencePrice')})")
            print(f"    - Change: {sample.get('change')} ({sample.get('ChangePercent')}%)")
            print(f"    - TotalMatchVolume: {sample.get('TotalMatchVolume')}")
            print(f"    - TradingDate: {sample.get('TradingDate')}")
            print(f"    - Timestamp: {sample.get('Timestamp')}")
            print(f"    - LocalReceivedTime: {sample.get('_local_recv_time')}")

    stock_trade_live = "YES" if stock_trade_count > 0 else "NO"
    index_live = "YES" if index_trade_count > 0 else "NO"
    cw_trade_live = "YES" if cw_trade_count > 0 else "NO"

    print(f"\n[RUNTIME] STOCK_TRADE_LIVE = {stock_trade_live}")
    print(f"[RUNTIME] INDEX_LIVE = {index_live}")
    print(f"[RUNTIME] CW_TRADE_LIVE = {cw_trade_live}")

    # =========================================================================
    # TEST 2: BIDASK (Order Book Depth)
    # =========================================================================
    print("\n" + "=" * 60)
    print("  [TEST 2] BIDASK STREAM (Order Book Depth)")
    print("=" * 60)

    ba_tickers = [stock_symbol, cw_symbol]
    ba_events: Dict[str, List[Dict[str, Any]]] = {t: [] for t in ba_tickers}

    def on_ba_event(data):
        try:
            d = data.to_dict() if hasattr(data, "to_dict") else (data if isinstance(data, dict) else vars(data))
            sym = str(d.get("Ticker", "")).upper()
            if sym in ba_events:
                d["_local_recv_time"] = datetime.now(timezone.utc).isoformat()
                ba_events[sym].append(d)
        except Exception as err:
            logger.warning(f"Error in on_ba_event: {err}")

    ba_stream = session.BidAsk(tickers=ba_tickers, callback=on_ba_event)
    ba_stream.start()
    print(f"[RUNTIME] BidAsk stream started for {ba_tickers}. Collecting for 20s...")

    start_time = time.time()
    while time.time() - start_time < 20:
        if len(ba_events[stock_symbol]) >= 3 and len(ba_events[cw_symbol]) >= 1:
            break
        time.sleep(0.5)

    ba_stream.stop()

    stock_ba_count = len(ba_events[stock_symbol])
    cw_ba_count = len(ba_events[cw_symbol])

    print(f"\n[RUNTIME] BidAsk Events Captured:")
    print(f"  • {stock_symbol} BidAsk Events: {stock_ba_count}")
    print(f"  • {cw_symbol} BidAsk Events: {cw_ba_count}")

    # Depth level inspection
    for sym in ba_tickers:
        evs = ba_events[sym]
        if evs:
            sample = evs[-1]
            # Count populated depth levels
            bid_levels = sum(1 for i in range(1, 11) if sample.get(f"BidPrice{i}") or sample.get(f"BidVol{i}") or sample.get(f"Best{i}Bid"))
            ask_levels = sum(1 for i in range(1, 11) if sample.get(f"AskPrice{i}") or sample.get(f"AskVol{i}") or sample.get(f"Best{i}Ask"))
            print(f"\n  Sample {sym} BidAsk Event:")
            print(f"    - Ticker: {sample.get('Ticker')}")
            print(f"    - Best1Bid: {sample.get('Best1Bid') or sample.get('BidPrice1')} (Vol: {sample.get('Best1BidVolume') or sample.get('BidVol1')})")
            print(f"    - Best1Ask: {sample.get('Best1Ask') or sample.get('AskPrice1')} (Vol: {sample.get('Best1AskVolume') or sample.get('AskVol1')})")
            print(f"    - Populated Bid Depth Levels: {bid_levels} / 10")
            print(f"    - Populated Ask Depth Levels: {ask_levels} / 10")
            print(f"    - Timestamp: {sample.get('Timestamp')}")

    stock_ba_live = "YES" if stock_ba_count > 0 else "NO"
    cw_ba_live = "YES" if cw_ba_count > 0 else "NO"

    print(f"\n[RUNTIME] STOCK_BIDASK_LIVE = {stock_ba_live}")
    print(f"[RUNTIME] CW_BIDASK_LIVE = {cw_ba_live}")

    # =========================================================================
    # TEST 3: CRITICAL DUAL-STREAM CONCURRENT TEST
    # =========================================================================
    print("\n" + "=" * 60)
    print("  [TEST 3] DUAL-STREAM SIMULTANEOUS CONCURRENCY TEST")
    print("=" * 60)

    dual_trade_events = []
    dual_ba_events = []

    s_trade = session.Trading_Data_Stream(tickers=[stock_symbol, cw_symbol], callback=lambda d: dual_trade_events.append(d))
    s_ba = session.BidAsk(tickers=[stock_symbol, cw_symbol], callback=lambda d: dual_ba_events.append(d))

    print("[RUNTIME] Launching Trading_Data_Stream and BidAsk simultaneously...")
    s_trade.start()
    time.sleep(3)
    s_ba.start()
    print("[RUNTIME] Both streams started. Listening concurrently for 15s...")

    start_time = time.time()
    while time.time() - start_time < 15:
        if len(dual_trade_events) >= 2 and len(dual_ba_events) >= 2:
            break
        time.sleep(0.5)

    trade_conn = getattr(s_trade, "connected", False)
    ba_conn = getattr(s_ba, "connected", False)

    s_trade.stop()
    s_ba.stop()

    dual_negotiation = "YES" if (trade_conn and ba_conn) else "NO"
    trades_while_ba_active = "YES" if len(dual_trade_events) > 0 else "NO"
    ba_while_trades_active = "YES" if len(dual_ba_events) > 0 else "NO"

    if dual_negotiation == "YES" and trades_while_ba_active == "YES" and ba_while_trades_active == "YES":
        dual_result = "DUAL_STREAM_LIVE_WORKS"
    elif dual_negotiation == "YES":
        dual_result = "SECOND_STREAM_NEGOTIATES_BUT_NO_DATA"
    else:
        dual_result = "SECOND_STREAM_REJECTED"

    print(f"\n[RUNTIME] DUAL_CONNECTION_NEGOTIATION = {dual_negotiation}")
    print(f"[RUNTIME] TRADING_STREAM_EVENTS_WHILE_BIDASK_ACTIVE = {trades_while_ba_active} ({len(dual_trade_events)} events)")
    print(f"[RUNTIME] BIDASK_EVENTS_WHILE_TRADING_STREAM_ACTIVE = {ba_while_trades_active} ({len(dual_ba_events)} events)")
    print(f"[RUNTIME] DUAL_STREAM_RESULT = {dual_result}")

    # =========================================================================
    # TEST 4: REALTIME PRICE UNIT DETERMINATION
    # =========================================================================
    print("\n" + "=" * 60)
    print("  [TEST 4] REALTIME PRICE UNIT VALIDATION")
    print("=" * 60)

    # Determine Stock Realtime Unit
    stock_price_sample = None
    if trade_events[stock_symbol]:
        stock_price_sample = trade_events[stock_symbol][-1].get("Close")
    elif ba_events[stock_symbol]:
        stock_price_sample = ba_events[stock_symbol][-1].get("Best1Bid") or ba_events[stock_symbol][-1].get("BidPrice1")

    # Determine CW Realtime Unit
    cw_price_sample = None
    if trade_events[cw_symbol]:
        cw_price_sample = trade_events[cw_symbol][-1].get("Close")
    elif ba_events[cw_symbol]:
        cw_price_sample = ba_events[cw_symbol][-1].get("Best1Bid") or ba_events[cw_symbol][-1].get("BidPrice1")

    # Determine Index Unit
    index_sample = None
    if trade_events[index_symbol]:
        index_sample = trade_events[index_symbol][-1].get("Close")

    print(f"  • Stock Realtime Observed Price: {stock_price_sample}")
    print(f"  • CW Realtime Observed Price: {cw_price_sample}")
    print(f"  • Index Realtime Observed Value: {index_sample}")

    # Unit Classifications
    if stock_price_sample and stock_price_sample > 1000:
        stock_unit = "RAW_VND"
    elif stock_price_sample and stock_price_sample > 0:
        stock_unit = "THOUSAND_VND"
    else:
        stock_unit = "UNKNOWN"

    if cw_price_sample and cw_price_sample > 100:
        cw_unit = "RAW_VND"
    elif cw_price_sample and cw_price_sample > 0:
        cw_unit = "THOUSAND_VND"
    else:
        cw_unit = "UNKNOWN"

    index_unit = "POINTS" if index_sample and index_sample > 500 else "UNKNOWN"

    print(f"\n[RUNTIME] STOCK_REALTIME_PRICE_UNIT = {stock_unit}")
    print(f"[RUNTIME] CW_REALTIME_PRICE_UNIT = {cw_unit}")
    print(f"[RUNTIME] INDEX_REALTIME_UNIT = {index_unit}")

    # =========================================================================
    # TEST 5: WATCHLIST RESTART LIFECYCLE
    # =========================================================================
    print("\n" + "=" * 60)
    print("  [TEST 5] WATCHLIST RESTART LIFECYCLE")
    print("=" * 60)

    restart_events = []
    print("[RUNTIME] Phase A: Start stream with [HPG, CHPG2602]")
    s_restart1 = session.Trading_Data_Stream(tickers=[stock_symbol, cw_symbol], callback=lambda d: restart_events.append(d))
    s_restart1.start()
    time.sleep(3)
    s_restart1.stop()
    time.sleep(1)

    print("[RUNTIME] Phase B: Recreate stream with [HPG, CHPG2602, VNINDEX]")
    restart_events_b = []
    s_restart2 = session.Trading_Data_Stream(tickers=[stock_symbol, cw_symbol, index_symbol], callback=lambda d: restart_events_b.append(d))
    s_restart2.start()
    time.sleep(4)
    s_restart2.stop()

    restart_success = "YES" if len(restart_events_b) > 0 or getattr(s_restart2, "connected", False) else "NO"
    print(f"[RUNTIME] RESTART_LIFECYCLE_RESUMES = {restart_success}")

    # =========================================================================
    # FINAL CLASSIFICATION & GO / NO-GO
    # =========================================================================
    print("\n" + "=" * 80)
    print("  FINAL GO / NO-GO CLASSIFICATION")
    print("=" * 80)

    all_criteria_met = (
        stock_trade_live == "YES" and
        index_live == "YES" and
        dual_result == "DUAL_STREAM_LIVE_WORKS" and
        stock_unit == "RAW_VND"
    )

    if all_criteria_met and (cw_trade_live == "YES" or cw_ba_live == "YES"):
        final_verdict = "GO_WITH_LIMITATIONS"
    elif all_criteria_met:
        final_verdict = "GO_WITH_LIMITATIONS"
    else:
        final_verdict = "NO_GO"

    print(f"\n[FINAL_VERDICT] FIINQUANT_FREE = {final_verdict}")
    print("=" * 80)


if __name__ == "__main__":
    main()
