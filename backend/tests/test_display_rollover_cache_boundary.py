"""An off-session cache must not outlive the 08:00 ICT display rollover.

Reported 2026-09-08 at 08:44 ICT: the index cards showed VN30 1,963.01 from 2026-09-07
while the watchlist beside them had already blanked for 2026-09-08. Two different
boundaries in one board - the dashboard rolls at 08:00, but the overview cache stretched to
the 09:00 OPEN, so for that hour every morning the two surfaces described different days.
"""
from datetime import datetime

import pytest

from app.market_data import trading_calendar as cal
from app.market_data.market_session import market_session
from app.market_data.providers.fiinquant_provider import FiinQuantProvider
from app.market_data.session_reference import reference_session_date
from app.market_data.trading_calendar import VN_TZ


def _ict(iso: str) -> datetime:
    return datetime.fromisoformat(iso).replace(tzinfo=VN_TZ)


# 2026-09-07 Mon, 09-08 Tue, 09-11 Fri, 09-12 Sat, 09-13 Sun
@pytest.mark.parametrize("iso,hours", [
    ("2026-09-08T07:30", 0.5),    # just before the roll
    ("2026-09-07T15:30", 16.5),   # after the close, rolls next morning
    ("2026-09-11T16:00", 64.0),   # Friday evening -> Monday 08:00
    ("2026-09-12T10:00", 46.0),   # Saturday -> Monday 08:00
])
def test_the_rollover_boundary_is_0800_on_the_next_trading_day(iso, hours):
    assert market_session.seconds_until_display_rollover(_ict(iso)) == pytest.approx(hours * 3600)


def test_the_rollover_is_earlier_than_the_open_on_the_evening_before():
    """The whole bug: these two are different instants, and the cache used the wrong one."""
    evening = _ict("2026-09-07T15:30")
    assert (market_session.seconds_until_display_rollover(evening)
            < market_session.seconds_until_next_trading_session(evening))


def test_it_lands_exactly_where_the_displayed_session_changes():
    """The boundary must be the same one reference_session_date uses, not merely close."""
    before = _ict("2026-09-08T07:59:59")
    secs = market_session.seconds_until_display_rollover(before)
    after = before.timestamp() + secs
    assert reference_session_date(before) != reference_session_date(
        datetime.fromtimestamp(after, VN_TZ)
    )


def _provider(*, active: bool, to_open: float, to_roll: float) -> FiinQuantProvider:
    p = FiinQuantProvider(username="t", password="t", max_symbols=33)
    p._market_is_active = lambda: active
    p._seconds_to_next_session = lambda: to_open
    p._seconds_to_display_rollover = lambda: to_roll
    return p


def test_the_cache_expires_at_the_rollover_not_at_the_open():
    """Overnight the roll comes first, so it is the one that bounds the cache."""
    p = _provider(active=False, to_open=17.5 * 3600, to_roll=16.5 * 3600)
    assert p._cache_ttl(15.0) == pytest.approx(16.5 * 3600)


def test_after_the_rollover_the_open_bounds_it_again():
    """Between 08:00 and 09:00 the next roll is ~23h away and the open minutes away; the
    cache must take the nearer bound, or it would sit unrefreshed through the open."""
    p = _provider(active=False, to_open=0.23 * 3600, to_roll=23.23 * 3600)
    assert p._cache_ttl(15.0) == pytest.approx(0.23 * 3600)


def test_an_in_session_cache_is_unaffected():
    p = _provider(active=True, to_open=0.0, to_roll=20 * 3600)
    assert p._cache_ttl(15.0) == 15.0


def test_an_unsettled_payload_still_ignores_both_boundaries():
    """A known-incomplete build keeps retrying - stretching it would strand the gap."""
    p = _provider(active=False, to_open=17.5 * 3600, to_roll=16.5 * 3600)
    assert p._cache_ttl(15.0, settled=False) == 15.0


def test_the_active_ttl_remains_a_floor():
    p = _provider(active=False, to_open=1.0, to_roll=2.0)
    assert p._cache_ttl(15.0) == 15.0


def test_a_calendar_fault_never_wedges_the_cache():
    p = _provider(active=False, to_open=17.5 * 3600, to_roll=0.0)

    def boom():
        raise RuntimeError("calendar exploded")

    p._seconds_to_display_rollover = boom
    assert p._cache_ttl(15.0) == 15.0


# --------------------------------------------------------------------------- #
# The service layer has the same cache, and it is the one that persists - so a payload
# built yesterday afternoon survived a restart and was still served at 08:51 the next
# morning, an hour after the board had rolled. Fixing only the provider's copy was fixing
# by instance again.
# --------------------------------------------------------------------------- #
def _service(*, active: bool, to_open: float, to_roll: float, settled: bool = True):
    from app.market_data.market_overview_service import MarketOverviewService

    svc = MarketOverviewService()
    svc._seconds_to_next_session = lambda: to_open
    svc._seconds_to_display_rollover = lambda: to_roll
    svc._cache = {
        "components": {"top_stock_volume": "AVAILABLE" if settled else "UNAVAILABLE"},
        "indices": [{"sparkline": [{"timestamp": "2026-09-07T09:00:00+07:00"}]}],
    }
    return svc


def test_the_service_cache_also_expires_at_the_rollover(monkeypatch):
    monkeypatch.setattr(market_session, "is_trading_active", lambda: False)
    svc = _service(active=False, to_open=17.5 * 3600, to_roll=16.5 * 3600)
    assert svc._ttl_seconds() == pytest.approx(16.5 * 3600)


def test_the_service_cache_takes_the_open_once_the_rollover_has_passed(monkeypatch):
    monkeypatch.setattr(market_session, "is_trading_active", lambda: False)
    svc = _service(active=False, to_open=0.23 * 3600, to_roll=23.23 * 3600)
    assert svc._ttl_seconds() == pytest.approx(0.23 * 3600)


def test_the_service_keeps_its_60s_floor_and_unsettled_retry(monkeypatch):
    monkeypatch.setattr(market_session, "is_trading_active", lambda: False)
    assert _service(active=False, to_open=5.0, to_roll=5.0)._ttl_seconds() == 60.0
    assert _service(active=False, to_open=17.5 * 3600, to_roll=16.5 * 3600,
                    settled=False)._ttl_seconds() == 60.0


def test_reconnect_pacing_still_uses_the_open_not_the_rollover():
    """Deliberately NOT changed: this paces a stream reconnect, and there is nothing to
    receive until trading resumes, so the open is the correct bound."""
    p = _provider(active=False, to_open=120.0, to_roll=1.0)
    assert p._compute_reconnect_delay() == pytest.approx(120.0)
