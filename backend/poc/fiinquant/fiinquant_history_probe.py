#!/usr/bin/env python3
"""
FiinQuant Historical Data & Metadata Probe
Project: cw-research-platform (Vendor Reconnaissance - Credentialled Test)

Evaluates FiinQuant Official Python SDK (FiinQuantX) for:
1. Historical EOD and Intraday Data (Fetch_Trading_Data) for Stock and CW
2. Ticker and Instrument Discovery (TickerList)
3. Covered Warrant Static Metadata (BasicInfor, strike, ratio, maturity, underlying)
"""

import os
import sys
import json
import logging

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


def main():
    load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

    username = os.getenv("FIINQUANT_USERNAME", "").strip()
    password = os.getenv("FIINQUANT_PASSWORD", "").strip()

    stock = os.getenv("FIINQUANT_TEST_STOCK_1", "HPG").strip().upper()
    cw_sym = os.getenv("FIINQUANT_TEST_CW_SYMBOL", "").strip().upper()

    print("=" * 70)
    print("  FIINQUANT HISTORICAL DATA & METADATA PROBE")
    print("=" * 70)

    # 1. Check credentials
    if not username or not password or username == "your_username_here":
        print("\n[RESULT] BLOCKED_BY_MISSING_CREDENTIALS")
        sys.exit(0)

    try:
        import FiinQuantX as fq
    except ImportError as e:
        print(f"[ERROR] FiinQuantX not installed: {e}")
        sys.exit(1)

    print("\n--- [1. AUTHENTICATION] ---")
    session = fq.FiinSession(username=username, password=password)
    try:
        session.login()
        print("[RUNTIME] AUTH_SUCCESS")
    except Exception as e:
        print(f"[RUNTIME] AUTH_FAILED: {e}")
        sys.exit(1)

    # Auto-discover CW if not configured
    if not cw_sym or cw_sym == "your_active_cw_symbol_here":
        try:
            tl = session.TickerList(ticker="CFPT")
            if hasattr(tl, "tickers") and tl.tickers:
                cw_sym = tl.tickers[0]
                print(f"[RUNTIME] Discovered active CW: {cw_sym}")
        except Exception as err:
            cw_sym = "CFPT2401"

    # 2. Historical Daily EOD Test for Stock & CW
    print(f"\n--- [2. HISTORICAL DAILY EOD TEST ({stock} & {cw_sym})] ---")
    try:
        data_stock_eod = session.Fetch_Trading_Data(
            tickers=[stock],
            fields=["Open", "High", "Low", "Close", "Volume"],
            period=1,
            by="Day",
            realtime=False
        )
        print(f"[RUNTIME] Historical Daily EOD for {stock}: SUCCESS ({len(data_stock_eod) if hasattr(data_stock_eod, '__len__') else 'data'} rows returned)")
        if hasattr(data_stock_eod, "head"):
            print(data_stock_eod.head(2))
    except Exception as e:
        print(f"[RUNTIME] Historical Daily EOD for {stock} FAILED: {e}")

    try:
        data_cw_eod = session.Fetch_Trading_Data(
            tickers=[cw_sym],
            fields=["Open", "High", "Low", "Close", "Volume"],
            period=1,
            by="Day",
            realtime=False
        )
        print(f"[RUNTIME] Historical Daily EOD for {cw_sym}: SUCCESS ({len(data_cw_eod) if hasattr(data_cw_eod, '__len__') else 'data'} rows returned)")
        if hasattr(data_cw_eod, "head"):
            print(data_cw_eod.head(2))
    except Exception as e:
        print(f"[RUNTIME] Historical Daily EOD for {cw_sym} FAILED: {e}")

    # 3. Historical Intraday Minute Test for Stock & CW
    print(f"\n--- [3. HISTORICAL INTRADAY MINUTE TEST ({stock} & {cw_sym})] ---")
    try:
        data_stock_min = session.Fetch_Trading_Data(
            tickers=[stock],
            fields=["Open", "High", "Low", "Close", "Volume"],
            period=1,
            by="Minute",
            realtime=False
        )
        print(f"[RUNTIME] Historical 1-Minute for {stock}: SUCCESS ({len(data_stock_min) if hasattr(data_stock_min, '__len__') else 'data'} rows returned)")
        if hasattr(data_stock_min, "head"):
            print(data_stock_min.head(2))
    except Exception as e:
        print(f"[RUNTIME] Historical 1-Minute for {stock} FAILED: {e}")

    try:
        data_cw_min = session.Fetch_Trading_Data(
            tickers=[cw_sym],
            fields=["Open", "High", "Low", "Close", "Volume"],
            period=1,
            by="Minute",
            realtime=False
        )
        print(f"[RUNTIME] Historical 1-Minute for {cw_sym}: SUCCESS ({len(data_cw_min) if hasattr(data_cw_min, '__len__') else 'data'} rows returned)")
        if hasattr(data_cw_min, "head"):
            print(data_cw_min.head(2))
    except Exception as e:
        print(f"[RUNTIME] Historical 1-Minute for {cw_sym} FAILED: {e}")

    # 4. CW Static Metadata Test
    print(f"\n--- [4. CW STATIC METADATA TEST] ---")
    try:
        info = session.BasicInfor(tickers=[cw_sym])
        print(f"[RUNTIME] BasicInfor for {cw_sym}: {info}")
    except Exception as e:
        print(f"[RUNTIME] BasicInfor exception for {cw_sym}: {e}")

    print("\n" + "=" * 70)
    print("  HISTORICAL PROBE COMPLETED")
    print("=" * 70)


if __name__ == "__main__":
    main()
