"""Canonical HOSE trading calendar (Step 13C). Deterministic - every case injects a
frozen Asia/Ho_Chi_Minh datetime."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from app.market_data import trading_calendar as cal
from app.market_data.trading_calendar import VN_TZ, MarketSessionStatus


def _vn(y, m, d, hh=0, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=VN_TZ)


# --- session status across the week ------------------------------------- #
@pytest.mark.parametrize(
    "dt,expected",
    [
        (_vn(2026, 3, 6, 9, 30), MarketSessionStatus.MORNING_SESSION),      # Fri active
        (_vn(2026, 3, 6, 12, 0), MarketSessionStatus.LUNCH_BREAK),          # Fri lunch
        (_vn(2026, 3, 6, 14, 0), MarketSessionStatus.AFTERNOON_SESSION),    # Fri afternoon
        (_vn(2026, 3, 6, 15, 30), MarketSessionStatus.CLOSED_POST_MARKET),  # Fri post-close
        (_vn(2026, 3, 7, 10, 0), MarketSessionStatus.CLOSED_WEEKEND),       # Sat
        (_vn(2026, 3, 8, 10, 0), MarketSessionStatus.CLOSED_WEEKEND),       # Sun
        (_vn(2026, 3, 9, 8, 0), MarketSessionStatus.CLOSED_PRE_OPEN),       # Mon pre-open
        (_vn(2026, 3, 9, 10, 0), MarketSessionStatus.MORNING_SESSION),      # Mon active
        (_vn(2026, 9, 2, 10, 0), MarketSessionStatus.CLOSED_HOLIDAY),       # National Day
        (_vn(2026, 2, 17, 10, 0), MarketSessionStatus.CLOSED_HOLIDAY),      # Tet (multi-day)
    ],
)
def test_session_status(dt, expected):
    assert cal.session_status(dt) is expected


# --- previous / latest / next ----------------------------------------- #
def test_previous_trading_session_skips_weekend():
    assert cal.previous_trading_session(date(2026, 3, 9)) == date(2026, 3, 6)  # Mon -> Fri


def test_previous_trading_session_skips_holiday_cluster():
    # 2026-09-03 (Thu) -> previous session is 2026-08-28 (Fri): Aug 31/Sep 1/Sep 2 are the
    # National Day holiday and Aug 29-30 the weekend.
    assert cal.previous_trading_session(date(2026, 9, 3)) == date(2026, 8, 28)


def test_latest_completed_session_on_saturday():
    assert cal.latest_completed_trading_session(_vn(2026, 8, 29, 10, 0)) == date(2026, 8, 28)


def test_latest_completed_session_before_close_is_prior_day():
    # Fri 2026-03-06 12:00 - today's bar is not final yet.
    assert cal.latest_completed_trading_session(_vn(2026, 3, 6, 12, 0)) == date(2026, 3, 5)


def test_latest_completed_session_after_close_is_today():
    assert cal.latest_completed_trading_session(_vn(2026, 3, 6, 15, 30)) == date(2026, 3, 6)


def test_latest_completed_session_across_holiday():
    # During the 2026 National Day cluster, latest completed session is 2026-08-28.
    assert cal.latest_completed_trading_session(_vn(2026, 9, 1, 12, 0)) == date(2026, 8, 28)


def test_next_trading_session_open_skips_holiday_cluster():
    got = cal.next_trading_session_open(_vn(2026, 8, 28, 16, 0))
    assert got == _vn(2026, 9, 3, 9, 0)  # first session after the National Day block


def test_year_boundary():
    # 2025-12-31 is a Wed trading day; 2026-01-01/02 are New Year holidays; 2026-01-05 Mon.
    assert cal.latest_completed_trading_session(_vn(2026, 1, 2, 12, 0)) == date(2025, 12, 31)
    assert cal.previous_trading_session(date(2026, 1, 5)) == date(2025, 12, 31)


# --- confidence ------------------------------------------------------- #
def test_calendar_confidence():
    assert cal.calendar_confidence(date(2026, 3, 2)) == "AUTHORITATIVE"
    assert cal.calendar_confidence(date(2027, 3, 2)) == "APPROXIMATE"   # provisional table
    assert cal.calendar_confidence(date(2031, 3, 2)) == "APPROXIMATE"   # no table at all


def test_beyond_known_horizon_still_excludes_fixed_holidays():
    # 2031 has no table; 1 Jan / 30 Apr / 1 May / 2 Sep are still non-trading.
    assert cal.is_trading_day(date(2031, 5, 1)) is False
    assert cal.is_trading_day(date(2031, 6, 3)) is True  # ordinary Tuesday


# --- overrides ------------------------------------------------------- #
def test_overrides(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(
        settings, "EXCHANGE_CALENDAR_OVERRIDES_JSON",
        '{"extra_closures": ["2026-07-01"], "force_open": ["2026-01-01"]}',
    )
    cal.reload_overrides()
    try:
        assert cal.is_trading_day(date(2026, 7, 1)) is False  # forced closure
        assert cal.is_trading_day(date(2026, 1, 1)) is True   # forced open (normally New Year)
    finally:
        monkeypatch.setattr(settings, "EXCHANGE_CALENDAR_OVERRIDES_JSON", "")
        cal.reload_overrides()
