"""Deterministic tests for the VN trading-session helpers (delegating to trading_calendar).

All cases pass an explicit timezone-aware datetime, so results do not depend on the
wall-clock or the host timezone. Dates are in a plain week (2026-03-02..08) with no VN
exchange holiday - holiday behaviour is covered in test_trading_calendar.py.
"""

from datetime import datetime

from app.market_data.market_session import VN_TZ, MarketSession, MarketSessionStatus

S = MarketSession()


def _vn(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=VN_TZ)


def test_session_status_boundaries():
    # 2026-03-02 is a Monday, no holiday.
    assert S.get_session_status(_vn(2026, 3, 2, 8, 59)) is MarketSessionStatus.CLOSED_PRE_OPEN
    assert S.get_session_status(_vn(2026, 3, 2, 9, 0)) is MarketSessionStatus.MORNING_SESSION
    assert S.get_session_status(_vn(2026, 3, 2, 11, 29)) is MarketSessionStatus.MORNING_SESSION
    assert S.get_session_status(_vn(2026, 3, 2, 11, 30)) is MarketSessionStatus.LUNCH_BREAK
    assert S.get_session_status(_vn(2026, 3, 2, 12, 59)) is MarketSessionStatus.LUNCH_BREAK
    assert S.get_session_status(_vn(2026, 3, 2, 13, 0)) is MarketSessionStatus.AFTERNOON_SESSION
    assert S.get_session_status(_vn(2026, 3, 2, 14, 59)) is MarketSessionStatus.AFTERNOON_SESSION
    assert S.get_session_status(_vn(2026, 3, 2, 15, 0)) is MarketSessionStatus.CLOSED_POST_MARKET
    # 2026-03-07 / -08 is Sat / Sun.
    assert S.get_session_status(_vn(2026, 3, 7, 10, 0)) is MarketSessionStatus.CLOSED_WEEKEND
    assert S.get_session_status(_vn(2026, 3, 8, 10, 0)) is MarketSessionStatus.CLOSED_WEEKEND


def test_seconds_until_next_session_when_active_is_zero():
    assert S.seconds_until_next_trading_session(_vn(2026, 3, 2, 9, 30)) == 0.0
    assert S.seconds_until_next_trading_session(_vn(2026, 3, 2, 13, 30)) == 0.0


def test_seconds_until_next_session_pre_open():
    assert S.seconds_until_next_trading_session(_vn(2026, 3, 2, 8, 0)) == 3600.0


def test_seconds_until_next_session_lunch_break():
    assert S.seconds_until_next_trading_session(_vn(2026, 3, 2, 11, 45)) == 75 * 60


def test_seconds_until_next_session_post_close_rolls_to_next_morning():
    # 16:00 Mon -> 09:00 Tue = 17h
    assert S.seconds_until_next_trading_session(_vn(2026, 3, 2, 16, 0)) == 17 * 3600


def test_seconds_until_next_session_friday_evening_skips_weekend():
    # 2026-03-06 is a Friday. 16:00 Fri -> 09:00 Mon 2026-03-09.
    got = S.seconds_until_next_trading_session(_vn(2026, 3, 6, 16, 0))
    assert got == (3 * 24 * 3600) - (7 * 3600)  # 65h


def test_seconds_until_next_session_saturday_and_sunday():
    assert S.seconds_until_next_trading_session(_vn(2026, 3, 7, 12, 0)) == (2 * 24 * 3600) - (3 * 3600)
    assert S.seconds_until_next_trading_session(_vn(2026, 3, 8, 12, 0)) == (24 * 3600) - (3 * 3600)


def test_seconds_until_next_session_naive_datetime_is_treated_as_vn():
    naive = datetime(2026, 3, 2, 8, 0)
    assert S.seconds_until_next_trading_session(naive) == 3600.0
