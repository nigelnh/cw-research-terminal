from scripts.monitor_vnstock_realtime import assess

SESSION = "2026-09-09"


def _state():
    return {
        "session": SESSION,
        "live_consecutive": 0,
        "last_live_tick": None,
        "realtime_advancing_consecutive": 0,
        "last_realtime_quote_count": None,
        "preopen_ready_seen": False,
        "accepted": False,
    }


def _market(phase: str, *, active: bool, tick: str | None = None):
    return {
        "provider": "vnstock",
        "api_key_configured": True,
        "upstream_status": "LIVE" if active else "READY",
        "feed_fresh": active,
        "last_tick_at": tick,
        "sessionContext": {
            "displaySessionDate": SESSION,
            "marketPhase": phase,
            "marketSessionActive": active,
            "serverTime": f"{SESSION}T09:15:00+07:00",
        },
    }


def test_monitor_accepts_reference_only_preopen_without_zero_volume_rankings():
    indices = [{
        "symbol": symbol,
        "session_date": SESSION,
        "reference": 1000,
        "value": None,
        "sparkline": [],
    } for symbol in ("VN30", "VNINDEX", "VNFINLEAD", "VNDIAMOND")]
    rows = [{
        "Ref": 21.5,
        "Traded": None,
        "provenance": {"reference": {"sessionDate": SESSION}},
    }]
    sample = {
        "market": _market("PRE_OPEN", active=False),
        "overview": {"indices": indices, "top_stock_volume": [], "top_cw_volume": []},
        "dashboard": {"rows": rows},
    }

    report, state = assess(sample, _state(), required_live_samples=3)

    assert report["status"] == "PREOPEN_READY"
    assert state["preopen_ready_seen"] is True


def test_monitor_requires_advancing_live_ticks_before_acceptance():
    indices = [{
        "symbol": symbol,
        "session_date": SESSION,
        "reference": 1000,
        "value": 1001,
        "sparkline": [{"timestamp": f"{SESSION}T09:15:00+07:00", "value": 1001}],
    } for symbol in ("VN30", "VNINDEX")]
    rows = [{
        "Ref": 21.5,
        "Traded": 21.6,
        "Bid1_Prc": 21.55,
        "Ask1_Prc": 21.6,
        "provenance": {
            "quote": {"sessionDate": SESSION},
            "book": {"sessionDate": SESSION},
            "reference": {"sessionDate": SESSION},
        },
    }]
    overview = {
        "indices": indices,
        "top_stock_volume": [{"symbol": "HPG", "volume": 100}],
        "top_cw_volume": [{"symbol": "CHPG2625", "volume": 10}],
    }
    state = _state()
    first = {
        "market": _market("CONTINUOUS_AM", active=True, tick="2026-09-09T02:15:00+00:00"),
        "overview": overview,
        "dashboard": {"rows": rows},
    }
    report, state = assess(first, state, required_live_samples=2)
    assert report["status"] == "LIVE_STABILIZING"

    second = {
        **first,
        "market": _market("CONTINUOUS_AM", active=True, tick="2026-09-09T02:15:15+00:00"),
    }
    report, state = assess(second, state, required_live_samples=2)
    assert report["status"] == "LIVE_ACCEPTED"
    assert state["live_consecutive"] == 2


def test_monitor_reports_stock_push_and_cw_polling_separately():
    indices = [{
        "symbol": symbol, "session_date": SESSION, "reference": 1000, "value": 1001,
        "sparkline": [{"timestamp": f"{SESSION}T09:15:00+07:00", "value": 1001}],
    } for symbol in ("VN30", "VNINDEX")]
    rows = [{
        "Ref": 21.5, "Traded": 21.6, "Bid1_Prc": 21.55, "Ask1_Prc": 21.6,
        "provenance": {
            "quote": {"sessionDate": SESSION}, "book": {"sessionDate": SESSION},
            "reference": {"sessionDate": SESSION},
        },
    }]
    overview = {
        "indices": indices,
        "top_stock_volume": [{"symbol": "HPG", "volume": 100}],
        "top_cw_volume": [{"symbol": "CHPG2625", "volume": 10}],
    }
    state = _state()
    state["last_realtime_quote_count"] = 8
    state["realtime_advancing_consecutive"] = 1
    state["live_consecutive"] = 1
    state["last_live_tick"] = "2026-09-09T02:15:00+00:00"
    market = {
        **_market("CONTINUOUS_AM", active=True, tick="2026-09-09T02:15:15+00:00"),
        "transport_mode": "HYBRID",
        "realtime_socket_connected": True,
        "realtime_quote_count": 12,
        "realtime_observed_stock_count": 2,
        "realtime_observed_cw_count": 0,
        "realtime_observed_symbols": ["HPG", "MBB"],
    }

    report, _ = assess(
        {"market": market, "overview": overview, "dashboard": {"rows": rows}},
        state,
        required_live_samples=2,
    )

    assert report["status"] == "LIVE_ACCEPTED_STOCK_PUSH_CW_POLLING"
    assert report["realtime"]["stockObserved"] is True
    assert report["realtime"]["cwObserved"] is False
