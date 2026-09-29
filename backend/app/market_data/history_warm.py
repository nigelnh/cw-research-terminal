"""When the nightly daily-bar warm pass runs, and what it asks for.

This used to be a closure inside ``lifespan``, where no test could reach it - and it never
ran in production. ``market_session`` was imported only inside a different function in
``main.py``, so every tick raised ``NameError`` before doing anything, logged "history warm
pass failed; will retry next session" and slept five minutes, from the day it shipped
(#125). The daily-bar table was never warmed, and the first viewer of each chart paid the
25-second on-request gap-fill instead.

Here the decision is one method, ``tick``, that a test drives with its own clock, and every
name it touches is imported at module level where a missing one fails at import time.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime

from app.core.config import settings
from app.market_data.market_session import market_session
from app.market_data.session_reference import reference_session_date

logger = logging.getLogger(__name__)

#: A pass that raises is retried on the next tick, but not all night: a failure that
#: repeats this many times in one session is systemic, and hammering the upstream until
#: morning would not fix it.
MAX_ATTEMPTS_PER_SESSION = 3


class DailyBarWarmer:
    """Runs ``warm(symbols)`` once per session, after the close, over the live universe."""

    def __init__(
        self,
        *,
        warm: Callable[[list[str]], Awaitable[dict]],
        universe: Callable[[], list[str]],
        now_vn: Callable[[], datetime] | None = None,
        trading_active: Callable[[], bool] | None = None,
        session_date: Callable[[], str] | None = None,
    ) -> None:
        self._warm = warm
        self._universe = universe
        self._now_vn = now_vn or market_session.get_vn_now
        self._trading_active = trading_active or market_session.is_trading_active
        self._session_date = session_date or (lambda: reference_session_date().isoformat())
        self.warmed_session: str | None = None
        self._attempts: dict[str, int] = {}

    async def tick(self) -> dict | None:
        """One decision. Returns the pass result when a pass ran, otherwise ``None``."""
        if not settings.HISTORY_NIGHTLY_WARM_ENABLED:
            return None
        session = self._session_date()
        if self.warmed_session == session:
            return None
        if self._now_vn().hour < int(settings.HISTORY_NIGHTLY_WARM_HOUR_ICT):
            return None
        # Never compete with the live poller for the same upstream quota.
        if self._trading_active():
            return None
        if self._attempts.get(session, 0) >= MAX_ATTEMPTS_PER_SESSION:
            return None
        symbols = self._universe()
        if not symbols:
            return None

        self._attempts[session] = self._attempts.get(session, 0) + 1
        logger.info("history warm pass starting for %d symbols (%s)", len(symbols), session)
        result = await self._warm(symbols)
        # Marked only once the pass has returned. The old loop marked the session before
        # starting, so a pass that died half way was written off until the next day.
        self.warmed_session = session
        return result

    async def run(self, interval: float = 300.0) -> None:
        while True:
            await asyncio.sleep(interval)
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - a warm pass must never take the app down
                logger.exception("history warm pass failed; retrying on a later tick")
