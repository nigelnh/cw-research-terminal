"""Canonical HOSE (Ho Chi Minh Stock Exchange) trading calendar.

Single source of truth for:
  * intraday session boundaries (morning / lunch / afternoon),
  * which calendar dates are trading days (weekends + Vietnamese exchange holidays),
  * previous / next / latest-completed trading session lookups,
  * the freshness / EOD-fallback / DTE reasoning that depends on the above.

All reasoning is in ``Asia/Ho_Chi_Minh`` (fixed UTC+7, no DST). Every public function
accepts an injected ``now`` / ``d`` so tests can freeze time.

Holiday model
-------------
The exchange closure calendar is **hand-maintained** from the official HOSE "Notice of
trading holiday schedule" announcements (one per year, published ~Dec of the prior year),
cross-checked against VSD. ``_AUTHORITATIVE_YEARS`` lists the years whose full closure set
is confirmed. ``_PROVISIONAL_HOLIDAYS`` carries a best-effort set for the next year before
its official notice lands (from secondary market-calendar sources); those dates are still
honoured but ``calendar_confidence`` reports ``APPROXIMATE`` for them.

Beyond every table we know: weekends + the four fixed-date public holidays + an approximate
Lunar-New-Year window (shared with ``app.persistence.ingestion.trading_calendar``). Results
outside ``_AUTHORITATIVE_YEARS`` are ``APPROXIMATE``.

Exceptional closures / corrections need no code change: set ``EXCHANGE_CALENDAR_OVERRIDES_JSON``
(``{"extra_closures": ["YYYY-MM-DD", ...], "force_open": ["YYYY-MM-DD", ...]}``).

Government "make-up working Saturdays" (e.g. 2026-01-10, 2026-08-22) are irrelevant here:
HOSE never trades on a Saturday, and the official notices confirm it explicitly.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, time, timedelta, timezone
from enum import Enum
from typing import Iterable, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

# Vietnam is a fixed UTC+7 offset, no DST. Defined here (not imported from the persistence
# layer) so this module stays a dependency-light leaf - the whole market-data + persistence
# stack imports it. Identical value to ``app.persistence.market_time.VN_TZ``.
VN_TZ = timezone(timedelta(hours=7), name="Asia/Ho_Chi_Minh")

# --- intraday session schedule (continuous-trading windows) ---------------- #
MORNING_START = time(9, 0, 0)
MORNING_END = time(11, 30, 0)
AFTERNOON_START = time(13, 0, 0)
AFTERNOON_END = time(15, 0, 0)

ATO_END = time(9, 15, 0)
ATC_START = time(14, 30, 0)
ATC_END = time(14, 45, 0)


class MarketSessionStatus(str, Enum):
    MORNING_SESSION = "MORNING_SESSION"        # 09:00 - 11:30
    LUNCH_BREAK = "LUNCH_BREAK"                # 11:30 - 13:00 (paused)
    AFTERNOON_SESSION = "AFTERNOON_SESSION"    # 13:00 - 15:00
    CLOSED_PRE_OPEN = "CLOSED_PRE_OPEN"        # trading day, before 09:00
    CLOSED_POST_MARKET = "CLOSED_POST_MARKET"  # trading day, after 15:00
    CLOSED_WEEKEND = "CLOSED_WEEKEND"          # Saturday / Sunday
    CLOSED_HOLIDAY = "CLOSED_HOLIDAY"          # weekday exchange holiday


class MarketPhase(str, Enum):
    """Fine-grained HOSE phase, additive to the legacy coarse session status."""

    PRE_OPEN = "PRE_OPEN"
    ATO = "ATO"
    CONTINUOUS_AM = "CONTINUOUS_AM"
    LUNCH_BREAK = "LUNCH_BREAK"
    CONTINUOUS_PM = "CONTINUOUS_PM"
    ATC = "ATC"
    POST_CLOSE_NEGOTIATED = "POST_CLOSE_NEGOTIATED"
    CLOSED = "CLOSED"


# --------------------------------------------------------------------------- #
# Hand-maintained exchange closure calendar
# --------------------------------------------------------------------------- #
# Weekday dates HOSE does not trade. Weekends are handled separately.
_AUTHORITATIVE_HOLIDAYS: dict[int, frozenset[date]] = {
    2024: frozenset(
        {
            date(2024, 1, 1),                                    # Solar New Year
            date(2024, 2, 8), date(2024, 2, 9),                  # Tet (eve week)
            date(2024, 2, 12), date(2024, 2, 13), date(2024, 2, 14),  # Tet
            date(2024, 4, 18),                                   # Hung Kings' Day
            date(2024, 4, 30), date(2024, 5, 1),                 # Reunification + Labour
            date(2024, 9, 2), date(2024, 9, 3),                  # National Day (+ observed)
        }
    ),
    2025: frozenset(
        {
            date(2025, 1, 1),
            date(2025, 1, 27), date(2025, 1, 28), date(2025, 1, 29),
            date(2025, 1, 30), date(2025, 1, 31),                # Tet
            date(2025, 4, 7),                                    # Hung Kings' Day
            date(2025, 4, 30), date(2025, 5, 1), date(2025, 5, 2),  # Reunification + Labour (+ bridge)
            date(2025, 9, 1), date(2025, 9, 2),                  # National Day (2-day)
        }
    ),
    # Official HOSE notice dated 2025-12-09 ("Notice of trading holiday schedule for 2026").
    2026: frozenset(
        {
            date(2026, 1, 1), date(2026, 1, 2),                  # New Year (2-day)
            date(2026, 2, 16), date(2026, 2, 17), date(2026, 2, 18),
            date(2026, 2, 19), date(2026, 2, 20),                # Lunar New Year
            date(2026, 4, 27),                                   # Hung Kings' Day
            date(2026, 4, 30), date(2026, 5, 1),                 # Liberation + Labour
            date(2026, 8, 31), date(2026, 9, 1), date(2026, 9, 2),  # National Day (3-day)
        }
    ),
}

# Best-effort until HOSE publishes the official notice (~Dec 2026). Honoured, but
# ``calendar_confidence`` reports APPROXIMATE for these dates.
_PROVISIONAL_HOLIDAYS: dict[int, frozenset[date]] = {
    2027: frozenset(
        {
            date(2027, 1, 1),
            date(2027, 2, 5), date(2027, 2, 8), date(2027, 2, 9),  # Tet (Feb 6-7 weekend)
            date(2027, 4, 16),                                   # Hung Kings' Day
            date(2027, 4, 30), date(2027, 5, 3),                 # Reunification + Labour bridge (May 1 = Sat)
            date(2027, 9, 2), date(2027, 9, 3),                  # National Day (+ observed)
        }
    ),
}

_AUTHORITATIVE_YEARS = frozenset(_AUTHORITATIVE_HOLIDAYS)

# Fallback for years with no table at all: fixed-date public holidays only.
_FIXED_HOLIDAY_MD: frozenset[tuple[int, int]] = frozenset(
    {(1, 1), (4, 30), (5, 1), (9, 2)}
)

# Approximate Lunar New Year (Tet) closure window per year, (start_md, end_md) inclusive -
# generous on both sides. Used only for years with no holiday table. Also consumed by the
# gap classifier (re-exported from app.persistence.ingestion.trading_calendar).
_TET_WINDOWS: dict[int, tuple[tuple[int, int], tuple[int, int]]] = {
    2023: ((1, 20), (1, 27)),
    2024: ((2, 8), (2, 15)),
    2025: ((1, 27), (2, 3)),
    2026: ((2, 16), (2, 20)),
    2027: ((2, 5), (2, 11)),
    2028: ((1, 25), (1, 31)),
}

_CONF_AUTHORITATIVE = "AUTHORITATIVE"
_CONF_APPROXIMATE = "APPROXIMATE"


def _parse_override_dates(raw: object) -> frozenset[date]:
    out: set[date] = set()
    if isinstance(raw, (list, tuple)):
        for item in raw:
            try:
                out.add(date.fromisoformat(str(item).strip()[:10]))
            except ValueError:
                logger.warning("EXCHANGE_CALENDAR_OVERRIDES_JSON: bad date %r ignored", item)
    return frozenset(out)


def _load_overrides() -> tuple[frozenset[date], frozenset[date]]:
    raw = getattr(settings, "EXCHANGE_CALENDAR_OVERRIDES_JSON", "") or ""
    if not raw.strip():
        return frozenset(), frozenset()
    try:
        obj = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("EXCHANGE_CALENDAR_OVERRIDES_JSON is not valid JSON; ignoring.")
        return frozenset(), frozenset()
    return (
        _parse_override_dates(obj.get("extra_closures")),
        _parse_override_dates(obj.get("force_open")),
    )


# Resolved once at import; cheap to recompute in tests via `reload_overrides()`.
_EXTRA_CLOSURES, _FORCE_OPEN = _load_overrides()


def reload_overrides() -> None:
    """Re-read ``EXCHANGE_CALENDAR_OVERRIDES_JSON`` (tests / hot config)."""
    global _EXTRA_CLOSURES, _FORCE_OPEN
    _EXTRA_CLOSURES, _FORCE_OPEN = _load_overrides()


# --------------------------------------------------------------------------- #
# Core predicates
# --------------------------------------------------------------------------- #
def is_weekend(d: date) -> bool:
    return d.weekday() >= 5  # 5 = Sat, 6 = Sun


def _table_holidays(year: int) -> frozenset[date]:
    return _AUTHORITATIVE_HOLIDAYS.get(year) or _PROVISIONAL_HOLIDAYS.get(year) or frozenset()


def _tet_window_holiday(d: date) -> bool:
    """Approximate Lunar-New-Year closure for years with no table (shared window)."""
    win = _TET_WINDOWS.get(d.year)
    if win is None:
        return False
    (sm, sd), (em, ed) = win
    return date(d.year, sm, sd) <= d <= date(d.year, em, ed)


def is_exchange_holiday(d: date) -> bool:
    """A weekday HOSE does not trade (excludes weekends).

    For a year with a confirmed HOSE notice the table is definitive. For a year without
    one, only the four fixed-date public holidays are treated as certain closures; the
    approximate Tet window is advisory (see ``in_tet_window``) and is NOT excluded from the
    "expected trading days" set - the gap classifier downgrades missing bars there instead.
    """
    if d in _FORCE_OPEN:
        return False
    if d in _EXTRA_CLOSURES:
        return True
    table = _table_holidays(d.year)
    if table:
        return d in table
    return (d.month, d.day) in _FIXED_HOLIDAY_MD


def is_trading_day(d: date) -> bool:
    try:
        return not is_weekend(d) and not is_exchange_holiday(d)
    except Exception:  # noqa: BLE001 - fail safe to weekend-only
        logger.exception("trading_calendar: is_trading_day(%s) failed; assuming weekday=trading", d)
        return not is_weekend(d)


def calendar_confidence(d: Optional[date] = None) -> str:
    """``AUTHORITATIVE`` when ``d``'s year has a confirmed HOSE notice, else ``APPROXIMATE``."""
    year = (d or _vn_now().date()).year
    if year in _AUTHORITATIVE_YEARS and d not in _EXTRA_CLOSURES and d not in _FORCE_OPEN:
        return _CONF_AUTHORITATIVE
    return _CONF_APPROXIMATE


# --------------------------------------------------------------------------- #
# Time-of-day / session status
# --------------------------------------------------------------------------- #
def _vn_now() -> datetime:
    return datetime.now(VN_TZ)


def _as_vn(dt: Optional[datetime]) -> datetime:
    if dt is None:
        return _vn_now()
    if dt.tzinfo is None:
        return dt.replace(tzinfo=VN_TZ)
    return dt.astimezone(VN_TZ)


def session_status(dt: Optional[datetime] = None) -> MarketSessionStatus:
    cur = _as_vn(dt)
    d = cur.date()
    if is_weekend(d):
        return MarketSessionStatus.CLOSED_WEEKEND
    if is_exchange_holiday(d):
        return MarketSessionStatus.CLOSED_HOLIDAY
    t = cur.time()
    if t < MORNING_START:
        return MarketSessionStatus.CLOSED_PRE_OPEN
    if MORNING_START <= t < MORNING_END:
        return MarketSessionStatus.MORNING_SESSION
    if MORNING_END <= t < AFTERNOON_START:
        return MarketSessionStatus.LUNCH_BREAK
    if AFTERNOON_START <= t < AFTERNOON_END:
        return MarketSessionStatus.AFTERNOON_SESSION
    return MarketSessionStatus.CLOSED_POST_MARKET


def market_phase(dt: Optional[datetime] = None) -> MarketPhase:
    """Expected HOSE phase from the exchange calendar.

    Provider ``MarketStatus`` remains a separately reported observation: undocumented
    vendor status codes are never translated into these values.
    """
    cur = _as_vn(dt)
    if not is_trading_day(cur.date()):
        return MarketPhase.CLOSED
    t = cur.time()
    if t < MORNING_START:
        return MarketPhase.PRE_OPEN
    if t < ATO_END:
        return MarketPhase.ATO
    if t < MORNING_END:
        return MarketPhase.CONTINUOUS_AM
    if t < AFTERNOON_START:
        return MarketPhase.LUNCH_BREAK
    if t < ATC_START:
        return MarketPhase.CONTINUOUS_PM
    if t < ATC_END:
        return MarketPhase.ATC
    if t < AFTERNOON_END:
        return MarketPhase.POST_CLOSE_NEGOTIATED
    return MarketPhase.CLOSED


def is_trading_active(dt: Optional[datetime] = None) -> bool:
    return session_status(dt) in (
        MarketSessionStatus.MORNING_SESSION,
        MarketSessionStatus.AFTERNOON_SESSION,
    )


# --------------------------------------------------------------------------- #
# Trading-session navigation
# --------------------------------------------------------------------------- #
def previous_trading_session(d: date) -> date:
    """The most recent trading day strictly before ``d``."""
    probe = d - timedelta(days=1)
    for _ in range(30):  # 30 days covers any VN holiday cluster
        if is_trading_day(probe):
            return probe
        probe -= timedelta(days=1)
    return probe  # pragma: no cover - unreachable in practice


def next_trading_day(d: date) -> date:
    """The first trading day strictly after ``d``."""
    probe = d + timedelta(days=1)
    for _ in range(30):
        if is_trading_day(probe):
            return probe
        probe += timedelta(days=1)
    return probe  # pragma: no cover


def latest_completed_trading_session(now: Optional[datetime] = None) -> date:
    """Most recent date whose 15:00 ICT close has passed. On a trading day before close,
    or on any non-trading day, this is the previous trading session."""
    cur = _as_vn(now)
    d = cur.date()
    close_today = datetime.combine(d, AFTERNOON_END, tzinfo=VN_TZ)
    if is_trading_day(d) and cur >= close_today:
        return d
    return previous_trading_session(d)


def current_or_next_trading_session_date(now: Optional[datetime] = None) -> date:
    cur = _as_vn(now)
    d = cur.date()
    if is_trading_day(d):
        return d
    return next_trading_day(d)


def next_trading_session_open(now: Optional[datetime] = None) -> datetime:
    """The next continuous-session open (09:00 or 13:00 ICT) strictly after ``now``."""
    cur = _as_vn(now)
    d = cur.date()
    for _ in range(40):
        if is_trading_day(d):
            for start in (MORNING_START, AFTERNOON_START):
                cand = datetime.combine(d, start, tzinfo=VN_TZ)
                if cand > cur:
                    return cand
        d = d + timedelta(days=1)
        cur = datetime.combine(d, time(0, 0), tzinfo=VN_TZ) - timedelta(seconds=1)
    return datetime.combine(d, MORNING_START, tzinfo=VN_TZ)  # pragma: no cover


def seconds_until_next_trading_session(now: Optional[datetime] = None) -> float:
    cur = _as_vn(now)
    if is_trading_active(cur):
        return 0.0
    return max(0.0, (next_trading_session_open(cur) - cur).total_seconds())


def trading_sessions_between(start: date, end: date) -> list[date]:
    """Trading days in ``[start, end]`` inclusive."""
    if start > end:
        return []
    out: list[date] = []
    d = start
    while d <= end:
        if is_trading_day(d):
            out.append(d)
        d += timedelta(days=1)
    return out


def expected_trading_days(start: date, end: date) -> list[date]:
    """Alias kept for the gap-classifier's vocabulary."""
    return trading_sessions_between(start, end)


def is_expected_trading_day(d: date) -> bool:
    return is_trading_day(d)


def sessions_to_maturity(session_date: date, maturity: date) -> int:
    """Count of trading sessions in ``(session_date, maturity]`` - a trading-day DTE."""
    if maturity <= session_date:
        return 0
    return len(trading_sessions_between(session_date + timedelta(days=1), maturity))


# Back-compat alias for the existing gap classifier import surface.
def last_completed_session_date(now_vn: Optional[datetime] = None) -> date:
    return latest_completed_trading_session(now_vn)


def in_tet_window(d: date) -> bool:
    """True inside the (approximate) Lunar-New-Year closure window for ``d``'s year."""
    return _tet_window_holiday(d) or (
        d in _table_holidays(d.year) and 1 <= d.month <= 2
    )


def iter_days(start: date, end: date) -> Iterable[date]:
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


# --------------------------------------------------------------------------- #
# Intraday-bar completeness (used by the ingestion mapper)
# --------------------------------------------------------------------------- #
TIMEFRAME_MINUTES: dict[str, int] = {
    "1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "1d": 24 * 60,
}


def intraday_bar_is_complete(
    bar_open_utc: datetime, timeframe_minutes: int, now_vn: Optional[datetime] = None
) -> bool:
    """An intraday bar is final once its close instant (open + Δ) is in the past."""
    now = _as_vn(now_vn)
    close_instant = bar_open_utc + timedelta(minutes=timeframe_minutes)
    return close_instant <= now


def is_fixed_holiday(d: date) -> bool:
    return (d.month, d.day) in _FIXED_HOLIDAY_MD
