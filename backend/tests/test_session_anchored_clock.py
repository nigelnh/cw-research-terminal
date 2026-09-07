"""The test-clock anchor must hold at every hour, or the rot it fixes just comes back.

Six tests in this suite failed at 00:46 ICT and passed during trading hours, because they
stamped cached quotes with "now" while hydration compares against the session being
DISPLAYED - which before the open, at a weekend or on a holiday is an earlier calendar day.
`display_session_ms` exists to close that gap; these cases pin the property that makes it
work, rather than re-checking it by hand whenever the suite is run at an odd hour.
"""
from datetime import datetime, timedelta

import pytest

from app.market_data import trading_calendar as cal
from app.market_data.session_reference import reference_session_date
from app.market_data.trading_calendar import VN_TZ
from tests.conftest import display_session_ms


def _ict(iso: str) -> datetime:
    return datetime.fromisoformat(iso).replace(tzinfo=VN_TZ)


# A weekday before the 08:00 display roll, mid-session, after the close, both weekend days,
# a public holiday, and the Tet closure - every shape of "now" the suite can run at.
INSTANTS = [
    "2026-09-07T00:46:00",  # the exact instant the six tests failed at
    "2026-09-07T07:59:00",  # one minute before the display roll
    "2026-09-07T08:00:00",  # the roll itself
    "2026-09-07T10:30:00",  # morning continuous session
    "2026-09-07T11:45:00",  # lunch break
    "2026-09-07T16:00:00",  # after the close
    "2026-09-07T23:59:00",
    "2026-09-12T03:00:00",  # Saturday
    "2026-09-13T14:00:00",  # Sunday
    "2026-01-01T09:00:00",  # public holiday
    "2026-02-17T11:00:00",  # inside the Tet closure window
]


@pytest.mark.parametrize("iso", INSTANTS)
def test_the_anchor_always_lands_inside_the_displayed_session(iso):
    """This is the property hydration checks: quote_dt.date() == display_day."""
    now = _ict(iso)
    anchored = datetime.fromtimestamp(display_session_ms(now=now) / 1000.0, tz=VN_TZ)
    assert anchored.date() == reference_session_date(now)


@pytest.mark.parametrize("iso", INSTANTS)
def test_the_displayed_session_is_always_a_real_trading_day(iso):
    """A quote anchored to a non-trading day would be a session that never happened."""
    assert cal.is_trading_day(reference_session_date(_ict(iso)))


@pytest.mark.parametrize("iso", INSTANTS)
def test_a_negative_offset_always_lands_before_the_displayed_session(iso):
    """The sanitization tests need a timestamp that is genuinely a previous session. "Now
    minus 24h" is not: just after midnight it lands inside the session still on screen."""
    now = _ict(iso)
    earlier = datetime.fromtimestamp(
        display_session_ms(-24 * 3600 * 1000, now=now) / 1000.0, tz=VN_TZ
    )
    assert earlier.date() < reference_session_date(now)


def test_the_anchor_is_inside_the_continuous_session_not_merely_on_the_right_day():
    """10:00 ICT has to actually be open, or a test could anchor to a moment the app treats
    as closed and get sanitized for a different reason."""
    day = reference_session_date(_ict("2026-09-07T10:30:00"))
    assert cal.session_status(datetime.combine(day, datetime.min.time(), tzinfo=VN_TZ)
                              .replace(hour=10)).value == "MORNING_SESSION"


def test_it_tracks_the_clock_rather_than_a_fixed_date():
    """The failure mode being prevented: a hard-coded date that is correct on the day it is
    written and wrong the next."""
    a = display_session_ms(now=_ict("2026-09-07T10:00:00"))
    b = display_session_ms(now=_ict("2026-09-07T10:00:00") + timedelta(days=7))
    assert a != b
