#!/usr/bin/env python3
"""Stateful production acceptance monitor for the Vnstock market feed.

The monitor only reads public, sanitized terminal endpoints.  A one-shot run is suitable
for a scheduler; repeated runs share a small state file and require multiple advancing
live observations before declaring the feed accepted.  Without ``--once`` it waits for
08:00 ICT and polls until acceptance or the configured deadline.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta
from datetime import time as wall_time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ICT = ZoneInfo("Asia/Ho_Chi_Minh")
EXPECTED_INDICES = {"VN30", "VNINDEX", "VNFINLEAD", "VNDIAMOND"}
ACTIVE_PHASES = {"ATO", "CONTINUOUS_AM", "CONTINUOUS_PM", "ATC"}
DEFAULT_BASE_URL = "https://backend-production-626f.up.railway.app"
DEFAULT_STATE = Path(__file__).resolve().parent / "out" / "vnstock-realtime-monitor-state.json"
DEFAULT_LOG = Path(__file__).resolve().parent / "out" / "vnstock-realtime-monitor.jsonl"


def _positive(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def _get_json(base_url: str, path: str, timeout: float) -> dict[str, Any]:
    request = Request(
        base_url.rstrip("/") + path,
        headers={"Accept": "application/json", "User-Agent": "cw-terminal-realtime-monitor/1"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{path}: {type(exc).__name__}") from exc
    if not isinstance(payload, dict):
        raise TypeError(f"{path}: invalid response shape")
    return payload


def _load_state(path: Path, session: str) -> dict[str, Any]:
    try:
        state = json.loads(path.read_text())
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        state = {}
    if state.get("session") != session:
        return {
            "session": session,
            "live_consecutive": 0,
            "last_live_tick": None,
            "realtime_advancing_consecutive": 0,
            "last_realtime_quote_count": None,
            "preopen_ready_seen": False,
            "accepted": False,
        }
    return state


def _save(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def _append(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")


def collect(base_url: str, timeout: float, symbols: list[str]) -> dict[str, Any]:
    market = _get_json(base_url, "/api/market/health", timeout)
    overview = _get_json(base_url, "/api/market/overview", timeout)
    dashboard = _get_json(
        base_url, "/api/market/dashboard?" + urlencode({"symbols": ",".join(symbols)}), timeout
    )
    return {"market": market, "overview": overview, "dashboard": dashboard}


def assess(sample: dict[str, Any], state: dict[str, Any], required_live_samples: int) -> tuple[dict[str, Any], dict[str, Any]]:
    market, overview, dashboard = (sample[key] for key in ("market", "overview", "dashboard"))
    context = market.get("sessionContext") or {}
    session = str(context.get("displaySessionDate") or "")
    phase = str(context.get("marketPhase") or market.get("market_phase") or "UNKNOWN")
    active = bool(context.get("marketSessionActive")) and phase in ACTIVE_PHASES
    rows = dashboard.get("rows") if isinstance(dashboard.get("rows"), list) else []
    indices = overview.get("indices") if isinstance(overview.get("indices"), list) else []
    stock_leaders = overview.get("top_stock_volume") if isinstance(overview.get("top_stock_volume"), list) else []
    cw_leaders = overview.get("top_cw_volume") if isinstance(overview.get("top_cw_volume"), list) else []

    provider_ok = (
        market.get("provider") == "vnstock"
        and market.get("api_key_configured") is True
        and market.get("upstream_status") not in {"UNAVAILABLE", "DISCONNECTED"}
    )
    by_index = {str(item.get("symbol")): item for item in indices if isinstance(item, dict)}
    current_indices = [
        item for item in by_index.values()
        if item.get("session_date") == session
    ]
    reference_only = (
        EXPECTED_INDICES.issubset(by_index)
        and all(
            item.get("session_date") == session
            and _positive(item.get("reference"))
            and item.get("value") is None
            and not item.get("sparkline")
            for item in by_index.values() if item.get("symbol") in EXPECTED_INDICES
        )
    )
    dashboard_references = bool(rows) and all(
        ((row.get("provenance") or {}).get("reference") or {}).get("sessionDate") == session
        and _positive(row.get("Ref"))
        and row.get("Traded") is None
        for row in rows
    )
    preopen_ready = bool(
        phase == "PRE_OPEN" and provider_ok and reference_only and dashboard_references
        and not stock_leaders and not cw_leaders
    )

    live_rows = [
        row for row in rows
        if ((row.get("provenance") or {}).get("quote") or {}).get("sessionDate") == session
        and _positive(row.get("Traded"))
    ]
    live_books = [
        row for row in rows
        if ((row.get("provenance") or {}).get("book") or {}).get("sessionDate") == session
        and (_positive(row.get("Bid1_Prc")) or _positive(row.get("Ask1_Prc")))
    ]
    index_live = [
        item for item in current_indices
        if _positive(item.get("value")) and bool(item.get("sparkline"))
    ]
    rankings_live = (
        bool(stock_leaders) and bool(cw_leaders)
        and all(_positive(item.get("volume")) for item in stock_leaders + cw_leaders)
    )
    last_tick = market.get("last_tick_at")
    hybrid = market.get("transport_mode") == "HYBRID"
    push_connected = market.get("realtime_socket_connected") is True
    push_stock = int(market.get("realtime_observed_stock_count") or 0) > 0
    push_cw = int(market.get("realtime_observed_cw_count") or 0) > 0
    realtime_quote_count = int(market.get("realtime_quote_count") or 0)
    prior_realtime_count = state.get("last_realtime_quote_count")
    push_advancing = bool(
        push_connected
        and prior_realtime_count is not None
        and realtime_quote_count > int(prior_realtime_count)
    )
    if push_advancing:
        state["realtime_advancing_consecutive"] = int(
            state.get("realtime_advancing_consecutive") or 0
        ) + 1
    elif hybrid and active:
        state["realtime_advancing_consecutive"] = 0
    state["last_realtime_quote_count"] = realtime_quote_count
    live_candidate = bool(
        active and provider_ok and market.get("feed_fresh") is True
        and market.get("upstream_status") == "LIVE"
        and last_tick and live_rows and live_books and len(index_live) >= 2 and rankings_live
    )

    if preopen_ready:
        state["preopen_ready_seen"] = True
    if live_candidate and last_tick != state.get("last_live_tick"):
        state["live_consecutive"] = int(state.get("live_consecutive") or 0) + 1
        state["last_live_tick"] = last_tick
    elif not live_candidate:
        state["live_consecutive"] = 0
    accepted = int(state.get("live_consecutive") or 0) >= required_live_samples
    state["accepted"] = accepted
    state["last_checked_at"] = context.get("serverTime")

    push_stable = int(state.get("realtime_advancing_consecutive") or 0) >= required_live_samples
    if accepted and hybrid and push_stable and push_stock and push_cw:
        status = "LIVE_ACCEPTED_HYBRID"
    elif accepted and hybrid and push_stable and push_stock:
        status = "LIVE_ACCEPTED_STOCK_PUSH_CW_POLLING"
    elif accepted and hybrid:
        status = "LIVE_ACCEPTED_POLLING_RECOVERY"
    elif accepted:
        status = "LIVE_ACCEPTED"
    elif phase == "PRE_OPEN":
        status = "PREOPEN_READY" if preopen_ready else "PREOPEN_MISMATCH"
    elif active:
        status = "LIVE_STABILIZING" if live_candidate else "LIVE_WAITING"
    else:
        status = "SESSION_PAUSED"

    report = {
        "status": status,
        "checkedAt": context.get("serverTime"),
        "session": session,
        "phase": phase,
        "provider": market.get("provider"),
        "upstream": market.get("upstream_status"),
        "feedFresh": market.get("feed_fresh"),
        "lastTickAt": last_tick,
        "preopenReady": preopen_ready,
        "preopenReadySeen": bool(state.get("preopen_ready_seen")),
        "liveConsecutive": int(state.get("live_consecutive") or 0),
        "requiredLiveSamples": required_live_samples,
        "realtime": {
            "transport": market.get("transport_mode"),
            "source": market.get("realtime_source"),
            "socketConnected": push_connected,
            "quoteCount": realtime_quote_count,
            "advancing": push_advancing,
            "advancingConsecutive": int(state.get("realtime_advancing_consecutive") or 0),
            "stockObserved": push_stock,
            "cwObserved": push_cw,
            "observedSymbols": market.get("realtime_observed_symbols") or [],
            "recommendation": (
                "SSI push confirmed for stocks and covered warrants."
                if push_stable and push_stock and push_cw
                else "Keep SSI for stocks and KBS polling for covered warrants."
                if push_stable and push_stock
                else "Terminal data is usable through KBS; SSI push still needs live-session evidence."
            ),
        },
        "checks": {
            "provider": provider_ok,
            "referenceOnlyIndices": reference_only,
            "blankPreopenRankings": not stock_leaders and not cw_leaders,
            "dashboardReferences": dashboard_references,
            "liveQuoteRows": len(live_rows),
            "liveBookRows": len(live_books),
            "liveIndices": len(index_live),
            "positiveRankings": rankings_live,
            "hybridConfigured": hybrid,
            "pushSocketConnected": push_connected,
            "pushStockCoverage": push_stock,
            "pushCwCoverage": push_cw,
        },
        "requestFailures": market.get("request_failure_count"),
        "feedStatus": (market.get("feedStatus") or {}).get("code"),
    }
    return report, state


def run_once(args: argparse.Namespace) -> dict[str, Any]:
    try:
        sample = collect(args.base_url, args.timeout, args.symbols)
        context = sample["market"].get("sessionContext") or {}
        session = str(context.get("displaySessionDate") or "unknown")
        state = _load_state(args.state_file, session)
        report, state = assess(sample, state, args.required_live_samples)
        _save(args.state_file, state)
    except Exception as exc:  # noqa: BLE001 - monitor must publish a bounded failure record
        report = {
            "status": "CHECK_FAILED", "checkedAt": datetime.now(ICT).isoformat(),
            "error": str(exc),
        }
    _append(args.log_file, report)
    print(json.dumps(report, ensure_ascii=False, separators=(",", ":")), flush=True)
    return report


def _next_start(now: datetime, start: wall_time) -> datetime:
    candidate = datetime.combine(now.date(), start, tzinfo=ICT)
    return max(candidate, now)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--symbols", nargs="+", default=["HPG", "CHPG2625"])
    parser.add_argument("--timeout", type=float, default=12.0)
    parser.add_argument("--interval", type=float, default=30.0)
    parser.add_argument("--required-live-samples", type=int, default=3)
    parser.add_argument("--start", default="08:00", help="ICT HH:MM")
    parser.add_argument("--deadline", default="11:30", help="ICT HH:MM")
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--log-file", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    if args.once:
        return 0 if run_once(args).get("status") != "CHECK_FAILED" else 2

    start = wall_time.fromisoformat(args.start)
    deadline = wall_time.fromisoformat(args.deadline)
    now = datetime.now(ICT)
    start_at = _next_start(now, start)
    if start_at > now:
        time.sleep((start_at - now).total_seconds())
    deadline_at = datetime.combine(datetime.now(ICT).date(), deadline, tzinfo=ICT)
    if deadline_at <= datetime.now(ICT):
        deadline_at += timedelta(days=1)
    while datetime.now(ICT) <= deadline_at:
        report = run_once(args)
        if str(report.get("status", "")).startswith("LIVE_ACCEPTED"):
            return 0
        time.sleep(max(5.0, args.interval))
    return 1


if __name__ == "__main__":
    sys.exit(main())
