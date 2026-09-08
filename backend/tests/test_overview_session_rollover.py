"""Past the 08:00 rollover, a previous session's overview is the wrong day, not stale data.

At 08:44 ICT on 2026-09-08 the index cards read VN30 1,963.01 from 2026-09-07 while the
watchlist beside them had blanked for 2026-09-08. Two TTL fixes (#82, #83) did not change
that, and measuring showed why: the cache was already 17.3h old and stale under BOTH
boundaries, so tightening the TTL was a no-op. Expiring faster only triggers a refresh, and
a refresh replaces the payload only if the provider answers - with the feed down, the old
cards persisted indefinitely. What the payload describes has to decide, not how old it is.
"""
from datetime import date

import pytest

from app.market_data.market_overview_service import MarketOverviewService
from app.market_data import market_overview_service as mod


def _cache(session: str) -> dict:
    return {
        "indices": [{
            "symbol": "VN30", "value": 1963.01, "availability": "AVAILABLE",
            "provenance": {"price": {"source": "FIINQUANT", "session_date": session}},
        }],
        "top_stock_volume": [{"symbol": "HPG"}],
        "top_cw_volume": [{"symbol": "CHPG2617"}],
        "as_of": f"{session}T14:45:00+07:00",
        "source": "FIINQUANT", "availability": "AVAILABLE",
        "components": {"top_stock_volume": "AVAILABLE"},
    }


def _svc(cache_session: str, display: str, monkeypatch) -> MarketOverviewService:
    svc = MarketOverviewService()
    svc._cache = _cache(cache_session)
    svc._cached_at = 0.0
    monkeypatch.setattr(mod, "reference_session_date", lambda *a, **k: date.fromisoformat(display))
    return svc


def test_a_previous_sessions_cards_are_not_served_after_the_rollover(monkeypatch):
    """The reported symptom, exactly: 09-07 cards at 08:44 on 09-08."""
    svc = _svc("2026-09-07", "2026-09-08", monkeypatch)
    out = svc._payload()
    assert out["indices"] == []
    assert out["availability"] == "UNAVAILABLE"
    assert out["previous_session_date"] == "2026-09-07"
    assert "2026-09-08" in out["unavailable_reason"]


def test_the_current_sessions_cards_are_served_normally(monkeypatch):
    svc = _svc("2026-09-08", "2026-09-08", monkeypatch)
    out = svc._payload()
    assert [i["symbol"] for i in out["indices"]] == ["VN30"]
    assert out["indices"][0]["value"] == 1963.01


def test_a_weekend_keeps_fridays_cards(monkeypatch):
    """`reference_session_date` holds the last completed session across a weekend, so
    Friday's cards ARE the displayed session and must not be cleared."""
    svc = _svc("2026-09-11", "2026-09-11", monkeypatch)
    assert svc._payload()["indices"] != []


def test_it_is_the_session_that_decides_not_the_age(monkeypatch):
    """A payload seconds old but from yesterday is still the wrong day."""
    import time as _t

    svc = _svc("2026-09-07", "2026-09-08", monkeypatch)
    svc._cached_at = _t.time()
    assert svc._payload()["indices"] == []


def test_a_payload_with_no_session_provenance_is_unavailable(monkeypatch):
    """Never blank a payload on a guess; without a dated card there is nothing to compare."""
    svc = _svc("2026-09-07", "2026-09-08", monkeypatch)
    svc._cache["indices"][0]["provenance"] = {}
    assert svc._payload()["indices"] == []


def test_the_empty_shape_still_carries_the_session_context(monkeypatch):
    svc = _svc("2026-09-07", "2026-09-08", monkeypatch)
    out = svc._payload()
    assert out["session_date"] == "2026-09-08"
    assert out["top_stock_volume"] == [] and out["top_cw_volume"] == []
    assert "market_phase" in out and "market_session_active" in out
