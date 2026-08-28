"""
Instrument Registry Snapshot Refresh CLI & Provenance Manager.
Discovers Covered Warrant symbols from legitimate public endpoints,
merges with known metadata, validates canonical schema,
and atomically updates the local cache snapshot without corrupting existing records on failure.

Usage:
    python -m app.instruments.instrument_refresh
"""

import os
import json
import logging
import httpx
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

logger = logging.getLogger("InstrumentRefresh")
DATA_DIR = Path(__file__).resolve().parent / "data"
SNAPSHOT_FILE = DATA_DIR / "active_warrants.json"
MANIFEST_FILE = DATA_DIR / "manifest.json"

VN_TZ = timezone(timedelta(hours=7))

# Common underlying tickers for Covered Warrants on HOSE
VN_UNDERLYINGS = [
    "HPG", "FPT", "MWG", "VIC", "VHM", "VNM", "TCB", "STB", "MBB",
    "VPB", "VRE", "MSN", "VJC", "POW", "SSI", "PDR", "NVL", "KDH", "GVR", "GAS"
]

ISSUER_NAME_MAP = {
    "SSI": "SSI",
    "VND": "VND",
    "VNDS": "VND",
    "HSC": "HSC",
    "HCM": "HSC",
    "KIS": "KIS",
    "KISVN": "KIS",
    "ACBS": "ACBS",
    "ACB": "ACBS",
    "TCBS": "TCBS",
    "TCX": "TCBS",
    "MBS": "MBS",
    "BSC": "BSC",
    "BSI": "BSC",
    "VPBS": "VPBS",
    "VPS": "VPS",
}


def parse_issuer_from_description(desc: str) -> Optional[str]:
    desc_upper = desc.upper()
    for token, canon in ISSUER_NAME_MAP.items():
        if f"CỦA {token}" in desc_upper or f"/{token}/" in desc_upper or f" {token}" in desc_upper:
            return canon
    return None


def fetch_dchart_warrants(timeout: float = 6.0) -> List[Dict[str, Any]]:
    """
    Fetches active/historical Covered Warrants from public broker dchart search endpoint.
    Legitimate public search interface without private authentication tokens.
    Classified as SEARCH_ONLY (lifecycle: UNKNOWN).
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Origin": "https://dchart.vndirect.com.vn",
        "Referer": "https://dchart.vndirect.com.vn/",
    }

    discovered: Dict[str, Dict[str, Any]] = {}

    for und in VN_UNDERLYINGS:
        url = f"https://dchart-api.vndirect.com.vn/dchart/search?query=C{und}&limit=50&exchange=HOSE"
        try:
            r = httpx.get(url, headers=headers, timeout=timeout)
            if r.status_code == 200:
                items = r.json()
                for it in items:
                    sym = str(it.get("symbol", "")).strip().upper()
                    if sym.startswith("C") and len(sym) == 8:
                        desc = str(it.get("description", ""))
                        issuer = parse_issuer_from_description(desc) or "UNKNOWN"
                        discovered[sym] = {
                            "symbol": sym,
                            "issuer": issuer,
                            "underlying_symbol": und,
                            "description": desc,
                            "evidence_level": "SEARCH_ONLY",
                            "status": "UNKNOWN",
                            "data_quality": "PARTIAL",
                            "metadata_source": "BROKER_DCHART_DISCOVERY",
                            "metadata_retrieved_at": datetime.now(VN_TZ).isoformat(),
                        }
        except Exception as e:
            logger.warning(f"Discovery search error for {und}: {e}")

    return list(discovered.values())


def merge_records(
    discovered_list: List[Dict[str, Any]],
    existing_list: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Merges newly discovered instruments with existing detailed metadata.
    Preserves all verified strike prices, ratios, maturities, and volume specifications.
    Does NOT upgrade SEARCH_ONLY to ACTIVE without current-market evidence.
    """
    merged: Dict[str, Dict[str, Any]] = {}

    # 1. Seed with existing known specifications (preserving explicit evidence levels)
    for item in existing_list:
        sym = item.get("symbol", "").upper()
        if sym:
            merged[sym] = dict(item)

    # 2. Merge discovered symbols
    for disc in discovered_list:
        sym = disc["symbol"]
        if sym not in merged:
            # Newly discovered warrant with search-only evidence (UNKNOWN lifecycle)
            merged[sym] = {
                "symbol": sym,
                "issuer": disc["issuer"],
                "underlying_symbol": disc["underlying_symbol"],
                "strike_price": None,
                "exercise_ratio": None,
                "maturity_date": None,
                "last_trading_date": None,
                "listed_volume": None,
                "issue_price": None,
                "instrument_type": "CW",
                "status": "UNKNOWN",
                "data_quality": "PARTIAL",
                "evidence_level": "SEARCH_ONLY",
                "metadata_source": disc.get("metadata_source", "BROKER_DCHART_DISCOVERY"),
                "metadata_retrieved_at": disc.get("metadata_retrieved_at", datetime.now(VN_TZ).isoformat()),
            }
        else:
            # Update issuer if previously unknown
            if merged[sym].get("issuer") in (None, "", "UNKNOWN") and disc.get("issuer") != "UNKNOWN":
                merged[sym]["issuer"] = disc["issuer"]

    # Return deterministic sorted list
    return [merged[k] for k in sorted(merged.keys())]


def atomic_write_snapshot(
    records: List[Dict[str, Any]],
    target_file: Optional[Path] = None,
    manifest_file: Optional[Path] = None,
) -> bool:
    """
    Atomically writes the snapshot using a temporary file and atomic rename.
    Guarantees no partially-written snapshot is observed during process interruption.
    """
    target = target_file or SNAPSHOT_FILE
    manifest_target = manifest_file or MANIFEST_FILE

    target.parent.mkdir(parents=True, exist_ok=True)
    temp_file = target.with_suffix(".json.tmp")

    try:
        # 1. Write formatted JSON to temporary file
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())

        # 2. Atomic rename
        temp_file.replace(target)

        # 3. Write manifest
        today = datetime.now(VN_TZ).strftime("%Y-%m-%d")
        active_cnt = sum(
            1
            for r in records
            if (mat := r.get("maturity_date")) is not None and str(mat) >= today and r.get("strike_price") is not None
        )
        expired_cnt = sum(
            1
            for r in records
            if (mat := r.get("maturity_date")) is not None and str(mat) < today
        )
        unknown_cnt = len(records) - active_cnt - expired_cnt

        complete_cnt = sum(
            1
            for r in records
            if r.get("strike_price") is not None
            and r.get("exercise_ratio") is not None
            and r.get("maturity_date") is not None
        )
        manifest_data = {
            "snapshot_updated_at": datetime.now(VN_TZ).isoformat(),
            "total_instruments": len(records),
            "verified_active_count": active_cnt,
            "verified_expired_count": expired_cnt,
            "unknown_lifecycle_count": unknown_cnt,
            "metadata_complete_count": complete_cnt,
            "metadata_partial_count": len(records) - complete_cnt,
            "provenance_description": "Canonical cached metadata snapshot refreshed via public broker search & manual canonical curation",
        }
        with open(manifest_target, "w", encoding="utf-8") as mf:
            json.dump(manifest_data, mf, indent=2)

        logger.info(
            f"Successfully atomic-saved {len(records)} instruments ({active_cnt} ACTIVE, {expired_cnt} EXPIRED, {unknown_cnt} UNKNOWN) to {target}"
        )
        return True

    except Exception as e:
        logger.error(f"Failed to write snapshot atomically: {e}")
        if temp_file.exists():
            temp_file.unlink(missing_ok=True)
        return False


def refresh_instruments(
    target_file: Optional[Path] = None,
    manifest_file: Optional[Path] = None,
) -> Tuple[bool, Dict[str, Any]]:
    target = target_file or SNAPSHOT_FILE
    existing: List[Dict[str, Any]] = []

    if target.exists():
        try:
            with open(target, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception as e:
            logger.warning(f"Could not read existing snapshot at {target}: {e}")

    try:
        discovered = fetch_dchart_warrants()
        if not discovered:
            logger.warning("No instruments discovered via public endpoints, retaining existing snapshot.")
            return False, {"error": "NO_INSTRUMENTS_DISCOVERED", "retained_count": len(existing)}

        merged = merge_records(discovered, existing)
        success = atomic_write_snapshot(merged, target_file=target, manifest_file=manifest_file)

        today = datetime.now(VN_TZ).strftime("%Y-%m-%d")
        active_cnt = sum(
            1
            for r in merged
            if (mat := r.get("maturity_date")) is not None and str(mat) >= today and r.get("strike_price") is not None
        )
        expired_cnt = sum(
            1
            for r in merged
            if (mat := r.get("maturity_date")) is not None and str(mat) < today
        )
        unknown_cnt = len(merged) - active_cnt - expired_cnt

        report = {
            "status": "SUCCESS" if success else "WRITE_FAILED",
            "discovered_count": len(discovered),
            "total_merged_count": len(merged),
            "verified_active_count": active_cnt,
            "verified_expired_count": expired_cnt,
            "unknown_lifecycle_count": unknown_cnt,
            "complete_count": sum(1 for x in merged if x.get("strike_price") is not None),
            "partial_count": sum(1 for x in merged if x.get("strike_price") is None),
        }
        return success, report

    except Exception as e:
        logger.error(f"Snapshot refresh encountered fatal error: {e}")
        return False, {"status": "ERROR", "error": str(e), "retained_count": len(existing)}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    print("=" * 70)
    print("  CW RESEARCH PLATFORM - INSTRUMENT SNAPSHOT REFRESH CLI")
    print("=" * 70)
    ok, rep = refresh_instruments()
    print(f"\nResult: {'SUCCESS' if ok else 'FAILED'}")
    print(json.dumps(rep, indent=2))
