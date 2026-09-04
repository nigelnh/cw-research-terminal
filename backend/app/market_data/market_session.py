"""Vietnam Market Trading Session & Realtime Display Eligibility Policy.

Thin adapter over the canonical :mod:`app.market_data.trading_calendar`. This module keeps
its long-standing public surface (``market_session`` singleton, ``MarketSessionStatus``,
``VN_TZ``) so existing imports are unaffected; all trading-day / holiday / session-boundary
logic now lives in one place.

Separation preserved:
- CACHE_RETENTION: Redis stores the latest canonical market snapshot across restarts.
- DISPLAY_ELIGIBILITY: a cached quote is presented as *live* only during an active session.
  Outside an active session (weekend, holiday, lunch, pre-open, post-close), realtime-only
  fields are not "live" - the after-hours resolver supplies clearly-labelled last-session
  values instead (Step 13C).
"""

from datetime import datetime
from typing import Optional

from app.market_data import trading_calendar as _cal
from app.market_data.trading_calendar import VN_TZ, MarketPhase, MarketSessionStatus

__all__ = ["MarketSession", "MarketSessionStatus", "MarketPhase", "VN_TZ", "market_session"]


class MarketSession:
    """Project-owned trading-session schedule + display-eligibility engine.

    Delegates every calendar decision to ``app.market_data.trading_calendar``.
    """

    # Retained as class attributes - a few call sites and tests read them.
    MORNING_START = _cal.MORNING_START
    MORNING_END = _cal.MORNING_END
    AFTERNOON_START = _cal.AFTERNOON_START
    AFTERNOON_END = _cal.AFTERNOON_END

    def get_vn_now(self) -> datetime:
        return datetime.now(VN_TZ)

    def get_session_status(self, dt: Optional[datetime] = None) -> MarketSessionStatus:
        return _cal.session_status(dt)

    def is_trading_active(self, dt: Optional[datetime] = None) -> bool:
        return _cal.is_trading_active(dt)

    def get_market_phase(self, dt: Optional[datetime] = None) -> MarketPhase:
        return _cal.market_phase(dt)

    def seconds_until_next_trading_session(self, dt: Optional[datetime] = None) -> float:
        return _cal.seconds_until_next_trading_session(dt)

    def is_display_eligible(
        self,
        received_timestamp_ms: Optional[int],
        dt: Optional[datetime] = None,
        max_age_seconds: int = 86400,
    ) -> bool:
        """Whether a quote may be presented as active realtime data.

        1. Outside an active trading session (incl. lunch, weekend, holiday): False.
        2. Within an active session: True only if the quote is fresh.
        """
        if not self.is_trading_active(dt):
            return False
        if received_timestamp_ms is None:
            return False
        current_dt = dt if dt is not None else self.get_vn_now()
        now_ms = int(current_dt.timestamp() * 1000)
        age_seconds = (now_ms - received_timestamp_ms) / 1000.0
        return 0 <= age_seconds <= max_age_seconds


market_session = MarketSession()
