"""
Vietnam Market Trading Session & Realtime Display Eligibility Policy.

Defines timezone-aware (Asia/Ho_Chi_Minh) trading session schedule for HOSE & HNX:
- Morning Session: 09:00:00 - 11:30:00
- Lunch Break:    11:30:00 - 13:00:00 (Trading paused)
- Afternoon:      13:00:00 - 15:00:00
- Closed:         Before 09:00, After 15:00, Weekends

Provides strict separation between:
- CACHE_RETENTION: Redis stores the latest canonical market snapshot across restarts/sessions.
- DISPLAY_ELIGIBILITY: Cached quotes are displayed as live realtime ONLY during active sessions.
  During lunch break or outside sessions, realtime-dependent fields strictly render as null (—).
"""

from datetime import datetime, time, timezone, timedelta
from enum import Enum
from typing import Optional

# Canonical Vietnam Timezone (UTC+7)
VN_TZ = timezone(timedelta(hours=7))


class MarketSessionStatus(str, Enum):
    MORNING_SESSION = "MORNING_SESSION"       # 09:00 - 11:30 Continuous / ATO
    LUNCH_BREAK = "LUNCH_BREAK"               # 11:30 - 13:00 Market Paused
    AFTERNOON_SESSION = "AFTERNOON_SESSION"   # 13:00 - 15:00 Continuous / ATC / PLO
    CLOSED_PRE_OPEN = "CLOSED_PRE_OPEN"       # 00:00 - 09:00
    CLOSED_POST_MARKET = "CLOSED_POST_MARKET" # 15:00 - 24:00
    CLOSED_WEEKEND = "CLOSED_WEEKEND"         # Saturday / Sunday


class MarketSession:
    """
    Explicit project-owned trading session schedule and display eligibility engine.
    Classified: PROJECT_DESIGN.
    """

    MORNING_START = time(9, 0, 0)
    MORNING_END = time(11, 30, 0)
    AFTERNOON_START = time(13, 0, 0)
    AFTERNOON_END = time(15, 0, 0)

    def get_vn_now(self) -> datetime:
        """Returns the current timezone-aware datetime in Asia/Ho_Chi_Minh (UTC+7)."""
        return datetime.now(VN_TZ)

    def get_session_status(self, dt: Optional[datetime] = None) -> MarketSessionStatus:
        """Evaluates market session status for a given datetime or current VN time."""
        current_dt = dt if dt is not None else self.get_vn_now()
        if current_dt.tzinfo is None:
            current_dt = current_dt.replace(tzinfo=VN_TZ)
        else:
            current_dt = current_dt.astimezone(VN_TZ)

        # 0 = Monday, ..., 4 = Friday, 5 = Saturday, 6 = Sunday
        weekday = current_dt.weekday()
        if weekday in (5, 6):
            return MarketSessionStatus.CLOSED_WEEKEND

        t = current_dt.time()

        if t < self.MORNING_START:
            return MarketSessionStatus.CLOSED_PRE_OPEN
        elif self.MORNING_START <= t < self.MORNING_END:
            return MarketSessionStatus.MORNING_SESSION
        elif self.MORNING_END <= t < self.AFTERNOON_START:
            return MarketSessionStatus.LUNCH_BREAK
        elif self.AFTERNOON_START <= t < self.AFTERNOON_END:
            return MarketSessionStatus.AFTERNOON_SESSION
        else:
            return MarketSessionStatus.CLOSED_POST_MARKET

    def is_trading_active(self, dt: Optional[datetime] = None) -> bool:
        """Returns True if the market is currently in an active trading session."""
        status = self.get_session_status(dt)
        return status in (MarketSessionStatus.MORNING_SESSION, MarketSessionStatus.AFTERNOON_SESSION)

    def seconds_until_next_trading_session(self, dt: Optional[datetime] = None) -> float:
        """Seconds from ``dt`` (or now, VN time) until the next continuous trading session
        begins - the 09:00 morning open or the 13:00 afternoon open, Monday-Friday.

        Returns ``0.0`` when a session is active right now. Public holidays are **not**
        modelled: on a VN holiday this returns the delta to the next clock-scheduled open,
        which is a safe (at worst slightly early) value for pacing reconnects.
        """
        current = dt if dt is not None else self.get_vn_now()
        if current.tzinfo is None:
            current = current.replace(tzinfo=VN_TZ)
        else:
            current = current.astimezone(VN_TZ)

        if self.is_trading_active(current):
            return 0.0

        # today .. +4 days covers a Friday-evening -> Monday-morning gap
        for add_days in range(0, 5):
            day = (current + timedelta(days=add_days)).date()
            if day.weekday() >= 5:  # Sat / Sun
                continue
            for start in (self.MORNING_START, self.AFTERNOON_START):
                candidate = datetime.combine(day, start, tzinfo=VN_TZ)
                if candidate > current:
                    return (candidate - current).total_seconds()

        return 3600.0  # unreachable in practice; conservative fallback

    def is_display_eligible(
        self,
        received_timestamp_ms: Optional[int],
        dt: Optional[datetime] = None,
        max_age_seconds: int = 86400,
    ) -> bool:
        """
        Determines whether a quote is eligible to be presented as active realtime data in the UI.

        Invariants:
        1. Outside active trading hours or during lunch break: Returns FALSE (renders em-dash).
        2. Within active session: Returns TRUE only if quote is fresh.
        """
        if not self.is_trading_active(dt):
            return False

        if received_timestamp_ms is None:
            return False

        current_dt = dt if dt is not None else self.get_vn_now()
        now_ms = int(current_dt.timestamp() * 1000)
        age_seconds = (now_ms - received_timestamp_ms) / 1000.0

        if age_seconds < 0 or age_seconds > max_age_seconds:
            return False

        return True


# Global session manager instance
market_session = MarketSession()
