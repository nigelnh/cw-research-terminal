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
#: morning would not fix it. Ticks that warm new symbols do not count against it.
MAX_FAILURES_PER_SESSION = 3

#: The window closes at the next morning's display rollover, before pre-open activity.
MORNING_CUTOFF_HOUR_ICT = 8


class DailyBarWarmer:
    """Warms, once per session and after the close, every symbol in the live universe.

    Incremental within a session: each tick warms the symbols not yet warmed for it. After
    a restart on 2026-09-29 the universe came up on its 30-symbol fallback, the pass ran
    over those 30 and marked the session done, and the 328 warrants that loaded later were
    never warmed. Now they are, on the next tick after they appear.
    """

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
        self._warmed: dict[str, set[str]] = {}
        self._failures: dict[str, int] = {}

    def warmed_symbols(self, session: str) -> frozenset[str]:
        return frozenset(self._warmed.get(session, ()))

    def _in_window(self) -> bool:
        # From the warm hour until the next morning. The old rule (hour >= warm hour) left
        # the small hours out, so a process restarted after midnight could not warm the
        # session it came up in until 16:00 the following day.
        hour = self._now_vn().hour
        return hour >= int(settings.HISTORY_NIGHTLY_WARM_HOUR_ICT) or hour < MORNING_CUTOFF_HOUR_ICT

    async def tick(self) -> dict | None:
        """One decision. Returns the pass result when a pass ran, otherwise ``None``."""
        if not settings.HISTORY_NIGHTLY_WARM_ENABLED or not self._in_window():
            return None
        # Never compete with the live poller for the same upstream quota.
        if self._trading_active():
            return None
        session = self._session_date()
        if self._failures.get(session, 0) >= MAX_FAILURES_PER_SESSION:
            return None
        for stale in [s for s in self._warmed if s != session]:
            del self._warmed[stale]
        warmed = self._warmed.setdefault(session, set())
        todo = [s for s in dict.fromkeys(self._universe()) if s and s not in warmed]
        if not todo:
            return None

        logger.info(
            "history warm pass starting for %d symbols (%s; %d already warmed this session)",
            len(todo), session, len(warmed),
        )
        try:
            result = await self._warm(todo)
        except Exception:
            self._failures[session] = self._failures.get(session, 0) + 1
            raise
        # Recorded only once the pass has returned; a pass that raised is retried.
        warmed.update(todo)
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
