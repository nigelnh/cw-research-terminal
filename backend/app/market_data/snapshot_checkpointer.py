"""Persists the last-valid realtime market snapshot for tracked instruments (Step 13C).

A single bounded background task, owned by the app lifespan (NOT the provider). It does not
write on every tick: per symbol it writes at most once per
``SNAPSHOT_CHECKPOINT_INTERVAL_SECONDS`` and only when the in-memory quote actually changed.
It also runs a full ``checkpoint(final=True)`` once when it first observes that the 15:00
ICT close has passed for the current session, and once on graceful shutdown - so a Railway
redeploy or crash before close does not lose the session's state, and after close the
dashboard has a FINAL row with the closing bid/ask.

Idempotency and regression guards live in ``SnapshotRepository.upsert``.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime
from typing import Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.market_data import trading_calendar as cal
from app.market_data.market_schemas import CanonicalQuote
from app.market_data.market_state import market_state
from app.persistence.repositories.snapshot_repository import SnapshotRepository, SnapshotRow

logger = logging.getLogger(__name__)


def _quote_fingerprint(q: CanonicalQuote) -> tuple:
    return (
        q.last_price, q.reference_price, q.price_change, q.total_volume,
        q.bid1_price, q.ask1_price, q.bid1_quantity, q.ask1_quantity,
        q.open_price, q.high_price, q.low_price, q.underlying_price,
    )


def _row_from_quote(sym: str, q: CanonicalQuote, *, session_date: date, source: str, quality: str) -> SnapshotRow:
    return SnapshotRow(
        symbol=sym,
        session_date=session_date,
        captured_at=datetime.now(cal.VN_TZ),
        source=source,
        quality=quality,
        instrument_type=q.instrument_type,
        reference_price=q.reference_price,
        last_price=q.last_price,
        price_change=q.price_change,
        price_change_percent=q.price_change_percent,
        open_price=q.open_price,
        high_price=q.high_price,
        low_price=q.low_price,
        average_price=q.average_price,
        total_volume=q.total_volume,
        trading_value=q.trading_value,
        bid1_price=q.bid1_price, bid1_quantity=q.bid1_quantity,
        ask1_price=q.ask1_price, ask1_quantity=q.ask1_quantity,
        bid2_price=q.bid2_price, bid2_quantity=q.bid2_quantity,
        ask2_price=q.ask2_price, ask2_quantity=q.ask2_quantity,
        bid3_price=q.bid3_price, bid3_quantity=q.bid3_quantity,
        ask3_price=q.ask3_price, ask3_quantity=q.ask3_quantity,
        underlying_symbol=q.underlying_symbol,
        underlying_price=q.underlying_price,
    )


class SnapshotCheckpointer:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        tracked_symbols: Callable[[], list[str]],
    ) -> None:
        self._sm = sessionmaker
        self._tracked = tracked_symbols
        self._interval = max(15, int(settings.SNAPSHOT_CHECKPOINT_INTERVAL_SECONDS))
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._last_fp: dict[str, tuple] = {}
        self._last_written_at: dict[str, float] = {}
        self._final_done_for: date | None = None
        self._counters = {"checkpoints": 0, "rows_written": 0, "final_runs": 0, "errors": 0}

    # -- lifecycle ------------------------------------------------------- #
    def start(self) -> None:
        if not settings.SNAPSHOT_ENABLED:
            logger.info("Snapshot checkpointer disabled (SNAPSHOT_ENABLED=false).")
            return
        if self._task is None or self._task.done():
            self._stop.clear()
            self._task = asyncio.create_task(self._run())
            logger.info("Snapshot checkpointer started (interval=%ss).", self._interval)

    async def stop(self) -> None:
        self._stop.set()
        if self._task and not self._task.done():
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._task.cancel()
        # Best-effort final flush on graceful shutdown.
        try:
            await self.checkpoint(final=True, reason="shutdown")
        except Exception as e:  # noqa: BLE001
            logger.warning("Snapshot final flush on shutdown failed: %s", e)

    # -- work ---------------------------------------------------------- #
    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        while not self._stop.is_set():
            try:
                now = datetime.now(cal.VN_TZ)
                # FINAL checkpoint once per session, shortly after 15:00 close.
                latest = cal.latest_completed_trading_session(now)
                if (
                    self._final_done_for != latest
                    and cal.is_trading_day(latest)
                    and now.date() == latest  # only stamp FINAL on the actual session day
                    and now.time() >= cal.AFTERNOON_END
                ):
                    await self.checkpoint(final=True, reason="session_close")
                    self._final_done_for = latest
                elif cal.is_trading_active(now) or cal.session_status(now).value == "LUNCH_BREAK":
                    await self.checkpoint(final=False, reason="interval", loop_time=loop.time())
            except asyncio.CancelledError:
                break
            except Exception as e:  # noqa: BLE001
                self._counters["errors"] += 1
                logger.warning("Snapshot checkpointer iteration error: %s", e)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
            except asyncio.TimeoutError:
                pass

    async def checkpoint(
        self, *, final: bool, reason: str, loop_time: float | None = None
    ) -> int:
        """Write snapshots for tracked symbols with a changed quote. Returns rows written."""
        symbols = [s.strip().upper() for s in (self._tracked() or []) if s and s.strip()]
        if not symbols:
            return 0
        now = datetime.now(cal.VN_TZ)
        session_date = cal.latest_completed_trading_session(now) if not cal.is_trading_day(now.date()) or now.time() < cal.MORNING_START else now.date()
        source = "SESSION_CLOSE" if final else "REALTIME_CHECKPOINT"
        quality = "FINAL" if final else "INTRADAY_CHECKPOINT"

        quotes = market_state.get_all_quotes()
        written = 0
        rows: list[SnapshotRow] = []
        for sym in symbols:
            q = quotes.get(sym)
            if q is None:
                continue
            fp = _quote_fingerprint(q)
            if not final:
                if self._last_fp.get(sym) == fp:
                    continue
                last_at = self._last_written_at.get(sym, 0.0)
                if loop_time is not None and last_at and (loop_time - last_at) < self._interval:
                    continue
            rows.append(_row_from_quote(sym, q, session_date=session_date, source=source, quality=quality))
            self._last_fp[sym] = fp
            if loop_time is not None:
                self._last_written_at[sym] = loop_time

        if not rows:
            return 0
        try:
            async with self._sm() as session:
                repo = SnapshotRepository(session)
                for r in rows:
                    await repo.upsert(r)
                    written += 1
                await session.commit()
        except Exception as e:  # noqa: BLE001
            self._counters["errors"] += 1
            logger.warning("Snapshot checkpoint write failed (%s): %s", reason, e)
            return 0

        self._counters["checkpoints"] += 1
        self._counters["rows_written"] += written
        if final:
            self._counters["final_runs"] += 1
        logger.info("Snapshot checkpoint [%s] wrote %d row(s) for session %s.", reason, written, session_date)
        return written

    def health(self) -> dict:
        return {
            "enabled": bool(settings.SNAPSHOT_ENABLED),
            "interval_seconds": self._interval,
            "final_done_for": self._final_done_for.isoformat() if self._final_done_for else None,
            "counters": dict(self._counters),
        }
