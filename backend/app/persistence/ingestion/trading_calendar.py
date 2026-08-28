"""Vietnam trading-day helpers for gap classification and completed-bar cutoffs.

The repo has **no** authoritative HOSE holiday calendar, and this module does not invent
one. It knows only:

* weekends are non-trading,
* a handful of *fixed-date* Vietnamese public holidays (New Year, Reunification Day,
  International Labour Day, National Day) are non-trading,
* the Lunar New Year (Tet) closes the exchange for roughly a week around late-Jan /
  mid-Feb - the exact dates shift every year, so we only mark an *approximate window* and
  classify anything inside it as ``UNKNOWN_CALENDAR`` rather than pretending to know.

Everything else that looks like a missing weekday session is reported as ``SUSPICIOUS``
for a human to judge.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from app.market_data.market_session import VN_TZ, MarketSession

_market_session = MarketSession()

# Fixed-date VN public holidays (month, day). Tet is handled separately (moves yearly).
_FIXED_HOLIDAYS: frozenset[tuple[int, int]] = frozenset(
    {
        (1, 1),    # Solar New Year's Day
        (4, 30),   # Reunification Day
        (5, 1),    # International Labour Day
        (9, 2),    # National Day
    }
)

# Approximate Lunar New Year (Tet) closure window per year: (start_md, end_md) inclusive,
# generous on both sides. Inside this window a missing session is UNKNOWN_CALENDAR, never
# SUSPICIOUS. Extend this dict as needed; absence of a year just means "no Tet hint".
_TET_WINDOWS: dict[int, tuple[tuple[int, int], tuple[int, int]]] = {
    2023: ((1, 20), (1, 27)),
    2024: ((2, 8), (2, 15)),
    2025: ((1, 27), (2, 3)),
    2026: ((2, 16), (2, 20)),
    2027: ((2, 5), (2, 11)),
}


def is_weekend(d: date) -> bool:
    return d.weekday() >= 5  # 5=Sat, 6=Sun


def is_fixed_holiday(d: date) -> bool:
    return (d.month, d.day) in _FIXED_HOLIDAYS


def in_tet_window(d: date) -> bool:
    win = _TET_WINDOWS.get(d.year)
    if win is None:
        return False
    (sm, sd), (em, ed) = win
    return date(d.year, sm, sd) <= d <= date(d.year, em, ed)


def is_expected_trading_day(d: date) -> bool:
    """Best-effort: a weekday that is not a known fixed holiday. Tet days still count as
    'expected' here - the gap classifier downgrades them to UNKNOWN_CALENDAR separately."""
    return not is_weekend(d) and not is_fixed_holiday(d)


def iter_days(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def expected_trading_days(start: date, end: date) -> list[date]:
    return [d for d in iter_days(start, end) if is_expected_trading_day(d)]


def last_completed_session_date(now_vn: datetime | None = None) -> date:
    """The most recent date whose *daily* bar is final.

    A session's 1D bar is complete only after the 15:00 ICT close. Before then (or on a
    non-trading day) the answer is the previous trading day.
    """
    now = now_vn.astimezone(VN_TZ) if now_vn is not None else _market_session.get_vn_now()
    d = now.date()
    close_today = datetime.combine(d, time(15, 0), tzinfo=VN_TZ)
    if is_expected_trading_day(d) and now >= close_today:
        return d
    # walk back to the previous expected trading day
    d -= timedelta(days=1)
    while not is_expected_trading_day(d):
        d -= timedelta(days=1)
    return d


def intraday_bar_is_complete(bar_open_utc: datetime, timeframe_minutes: int, now_vn: datetime | None = None) -> bool:
    """An intraday bar is final once its close instant (open + Δ) is in the past."""
    now = now_vn.astimezone(VN_TZ) if now_vn is not None else _market_session.get_vn_now()
    close_instant = bar_open_utc + timedelta(minutes=timeframe_minutes)
    return close_instant <= now


TIMEFRAME_MINUTES: dict[str, int] = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "1d": 24 * 60,
}
