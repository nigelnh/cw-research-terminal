"""Timeframe, price-basis and timestamp normalization for persisted market data.

Pure functions only - no database, no network. These define the canonical conventions
that every writer into ``market_bars`` MUST go through.

Conventions
-----------
Timezone
    Vietnam observes UTC+7 year-round and has never observed daylight saving. We model it
    as the fixed offset ``+07:00`` (``VN_TZ``). The host running this code may be on any
    timezone (or UTC in a container) - that is irrelevant because we never rely on the
    host clock's zone for bar timestamps.

Storage
    Every persisted timestamp column is PostgreSQL ``timestamptz`` and every value handed
    to the repository layer must be timezone-aware. Naive datetimes are rejected at the
    boundary (:func:`require_aware_utc`). Internally Postgres stores UTC.

Bar timestamp semantic
    ``market_bars.ts`` is the bar's OPEN instant, expressed in UTC.
    FiinQuant / FiinGroup label every bar by its start:
      * intraday ``"2026-08-20 09:15"`` is 09:15 *Vietnam wall-clock*  -> ``02:15:00Z``
      * daily    ``"2026-08-20"``       is the session's 00:00 Vietnam -> ``2026-08-19T17:00:00Z``
    ``market_bars.session_date`` carries the VN calendar date of the trading session and
    is the column to use for any human / calendar reasoning; never do ``DATE(ts)``.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Final

# Vietnam is a fixed UTC+7 offset, no DST, ever.
VN_TZ: Final = timezone(timedelta(hours=7), name="Asia/Ho_Chi_Minh")

# Canonical timeframe tokens persisted in ``market_bars.timeframe``.
CANONICAL_TIMEFRAMES: Final[frozenset[str]] = frozenset({"1m", "5m", "15m", "30m", "1h", "1d"})

# Canonical price-basis tokens persisted in ``market_bars.price_basis``.
PRICE_BASIS_ADJUSTED: Final = "ADJUSTED"
PRICE_BASIS_RAW: Final = "RAW"
CANONICAL_PRICE_BASES: Final[frozenset[str]] = frozenset({PRICE_BASIS_ADJUSTED, PRICE_BASIS_RAW})

# Accepted spellings -> canonical timeframe token.
_TIMEFRAME_ALIASES: Final[dict[str, str]] = {
    "1m": "1m", "1min": "1m", "minute": "1m", "m1": "1m",
    "5m": "5m", "5min": "5m", "m5": "5m",
    "15m": "15m", "15min": "15m", "m15": "15m",
    "30m": "30m", "30min": "30m", "m30": "30m",
    "1h": "1h", "60m": "1h", "hour": "1h", "h1": "1h",
    "1d": "1d", "d": "1d", "day": "1d", "daily": "1d", "1day": "1d", "eod": "1d",
}


def normalize_timeframe(value: str) -> str:
    """Map any accepted timeframe spelling to its canonical token (e.g. ``"1D"`` -> ``"1d"``)."""
    if not value:
        raise ValueError("timeframe must be a non-empty string")
    key = value.strip().lower()
    canonical = _TIMEFRAME_ALIASES.get(key)
    if canonical is None:
        raise ValueError(
            f"unsupported timeframe {value!r}; expected one of "
            f"{sorted(CANONICAL_TIMEFRAMES)} or a known alias"
        )
    return canonical


def is_intraday(timeframe: str) -> bool:
    return normalize_timeframe(timeframe) != "1d"


def normalize_price_basis(*, adjusted: bool) -> str:
    """``adjusted=True`` -> ``"ADJUSTED"``, else ``"RAW"``.

    FiinGroup only returns corporate-action-adjusted OHLC for ``type=Stock`` requests
    (the ``openPriceAdjusted``/``closePriceAdjusted``/... columns). Covered-warrant bars
    are always as-traded, so CW rows are always persisted as ``RAW`` regardless of the
    ``adjusted`` request flag.
    """
    return PRICE_BASIS_ADJUSTED if adjusted else PRICE_BASIS_RAW


def price_basis_to_adjusted(price_basis: str) -> bool:
    pb = price_basis.strip().upper()
    if pb not in CANONICAL_PRICE_BASES:
        raise ValueError(f"unknown price_basis {price_basis!r}")
    return pb == PRICE_BASIS_ADJUSTED


def require_aware_utc(value: datetime, *, field: str = "timestamp") -> datetime:
    """Return ``value`` converted to UTC, rejecting naive datetimes.

    This is the guard every repository method applies to datetime arguments so that no
    ambiguous naive datetime can ever reach a ``timestamptz`` column.
    """
    if not isinstance(value, datetime):
        raise TypeError(f"{field} must be a datetime, got {type(value).__name__}")
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(
            f"{field} must be timezone-aware; refusing to persist a naive datetime "
            f"({value!r}). Localize it (VN_TZ for Vietnam wall-clock) first."
        )
    return value.astimezone(timezone.utc)


def vn_session_date(ts_utc: datetime) -> date:
    """The Vietnam trading-session calendar date for a UTC instant.

    HOSE runs a single continuous daytime session (09:00-15:00 ICT) with no overnight
    wrap, so the session date is simply the VN-local calendar date.
    """
    return require_aware_utc(ts_utc, field="ts").astimezone(VN_TZ).date()


def daily_bar_open_utc(session_date: date) -> datetime:
    """UTC open instant for a daily bar: 00:00 Vietnam of the session date."""
    return datetime.combine(session_date, time(0, 0), tzinfo=VN_TZ).astimezone(timezone.utc)


def parse_vendor_timestamp(raw: str, *, timeframe: str) -> tuple[datetime, date]:
    """Normalize one FiinQuant ``timestamp`` string to ``(open_ts_utc, session_date)``.

    Accepts ``"YYYY-MM-DD"``, ``"YYYY-MM-DD HH:MM"`` and ``"YYYY-MM-DD HH:MM:SS"`` (and the
    ISO ``T`` separator). The wall-clock digits are interpreted as Vietnam local time
    (that is what FiinGroup's ``tradingDateId`` carries for intraday; the SDK strips the
    zone label). For daily bars only the date part is used and the open instant is
    midnight VN of that date.
    """
    tf = normalize_timeframe(timeframe)
    text = raw.strip().replace("T", " ")
    if not text:
        raise ValueError("empty vendor timestamp")

    date_part, _, time_part = text.partition(" ")
    y, m, d = (int(x) for x in date_part.split("-"))
    session = date(y, m, d)

    if tf == "1d" or not time_part:
        return daily_bar_open_utc(session), session

    hms = time_part.split(":")
    hh = int(hms[0])
    mm = int(hms[1]) if len(hms) > 1 else 0
    ss = int(hms[2]) if len(hms) > 2 else 0
    local = datetime(session.year, session.month, session.day, hh, mm, ss, tzinfo=VN_TZ)
    ts_utc = local.astimezone(timezone.utc)
    return ts_utc, local.date()
