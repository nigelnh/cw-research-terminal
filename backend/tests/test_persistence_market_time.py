"""Pure-unit tests for the persistence timestamp / timeframe / price-basis conventions.

No database. These pin the normalization rules every writer into ``market_bars`` obeys.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.persistence.market_time import (
    CANONICAL_TIMEFRAMES,
    VN_TZ,
    daily_bar_open_utc,
    normalize_price_basis,
    normalize_timeframe,
    parse_vendor_timestamp,
    price_basis_to_adjusted,
    require_aware_utc,
    vn_session_date,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1D", "1d"), ("1d", "1d"), ("daily", "1d"), ("Day", "1d"), ("eod", "1d"),
        ("1m", "1m"), ("1min", "1m"),
        ("5m", "5m"), ("5MIN", "5m"),
        ("15m", "15m"), ("30min", "30m"),
        ("1h", "1h"), ("60m", "1h"),
    ],
)
def test_normalize_timeframe_aliases(raw: str, expected: str):
    assert normalize_timeframe(raw) == expected
    assert expected in CANONICAL_TIMEFRAMES


def test_normalize_timeframe_rejects_unknown():
    with pytest.raises(ValueError):
        normalize_timeframe("2h")  # not in our canonical set
    with pytest.raises(ValueError):
        normalize_timeframe("")


def test_price_basis_roundtrip():
    assert normalize_price_basis(adjusted=True) == "ADJUSTED"
    assert normalize_price_basis(adjusted=False) == "RAW"
    assert price_basis_to_adjusted("ADJUSTED") is True
    assert price_basis_to_adjusted("raw") is False
    with pytest.raises(ValueError):
        price_basis_to_adjusted("SPLIT")


def test_require_aware_utc_rejects_naive():
    with pytest.raises(ValueError):
        require_aware_utc(datetime(2026, 8, 20, 9, 15))
    aware_vn = datetime(2026, 8, 20, 9, 15, tzinfo=VN_TZ)
    got = require_aware_utc(aware_vn)
    assert got.tzinfo == timezone.utc
    assert (got.hour, got.minute) == (2, 15)


def test_intraday_vendor_timestamp_is_vn_wallclock_to_utc():
    ts, session = parse_vendor_timestamp("2026-08-20 09:15", timeframe="5m")
    assert ts == datetime(2026, 8, 20, 2, 15, tzinfo=timezone.utc)
    assert session.isoformat() == "2026-08-20"

    ts2, _ = parse_vendor_timestamp("2026-08-20T13:45:00", timeframe="15m")
    assert ts2 == datetime(2026, 8, 20, 6, 45, tzinfo=timezone.utc)


def test_daily_vendor_timestamp_uses_session_date_and_vn_midnight():
    ts, session = parse_vendor_timestamp("2026-08-20", timeframe="1d")
    # VN midnight of 2026-08-20 == 2026-08-19 17:00 UTC
    assert ts == datetime(2026, 8, 19, 17, 0, tzinfo=timezone.utc)
    assert session.isoformat() == "2026-08-20"
    assert daily_bar_open_utc(session) == ts
    # a daily row's session_date must round-trip through vn_session_date
    assert vn_session_date(ts) == session


def test_vn_has_no_dst_january_equals_july_offset():
    jan = datetime(2026, 1, 15, 10, 0, tzinfo=VN_TZ)
    jul = datetime(2026, 7, 15, 10, 0, tzinfo=VN_TZ)
    assert jan.utcoffset() == jul.utcoffset()
    assert jan.astimezone(timezone.utc).hour == 3
    assert jul.astimezone(timezone.utc).hour == 3


def test_session_date_is_vn_local_date_not_utc_date():
    # 2026-08-20 01:00 VN  ->  2026-08-19 18:00 UTC  ->  session still 2026-08-20
    ts_utc = datetime(2026, 8, 19, 18, 0, tzinfo=timezone.utc)
    assert vn_session_date(ts_utc).isoformat() == "2026-08-20"
