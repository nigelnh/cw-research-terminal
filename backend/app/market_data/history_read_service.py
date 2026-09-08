"""PostgreSQL-first historical read path for ``/api/market/history`` (Step 7).

Decision flow for a request (daily timeframe, persistence enabled and reachable):

    resolve instrument + price basis (CW -> RAW, transparently)
    read PostgreSQL for the requested window
    assess coverage (present sessions vs session-aware expectations, bounded by
        listing/maturity, and the Step-6 gap classifier)
      * fully covered            -> return PostgreSQL rows, ZERO provider calls
      * missing in-horizon range -> ONE controlled provider gap-fill (single-flighted per
                                    stream via a PostgreSQL advisory lock), persist,
                                    re-read PostgreSQL, return
      * missing out-of-horizon   -> no provider call; return the truthful partial result

Non-daily timeframes, ``provider_direct`` mode, an unseeded symbol, or an unreachable DB
fall back to the legacy direct-provider path unchanged.

The wire shape is identical regardless of source. No internal DB fields are exposed.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import settings
from app.market_data.market_schemas import HistoricalBar
from app.persistence.ingestion.service import GapFillOutcome, IngestionService
from app.persistence.ingestion.trading_calendar import (
    expected_trading_days,
    in_tet_window,
    last_completed_session_date,
)
from app.persistence.market_time import VN_TZ, normalize_timeframe
from app.persistence.repositories.instrument_repository import InstrumentRepository
from app.persistence.repositories.market_bar_repository import MarketBarRepository

logger = logging.getLogger(__name__)


class HistoryRequestError(ValueError):
    """Invalid public history request (bad dates / span / timeframe). Maps to HTTP 400."""


@dataclass
class _CoverageAssessment:
    covered: bool
    fill_from: date | None
    fill_to: date | None
    reason: str
    missing_sessions: int = 0


class HistoryReadService:
    """Module singleton. ``configure()`` is called from the app lifespan when the
    persistence layer is enabled; otherwise the service stays in provider-direct mode."""

    def __init__(self) -> None:
        self._engine: AsyncEngine | None = None
        self._sm: async_sessionmaker[AsyncSession] | None = None
        self._provider = None  # HistoricalBarProvider (FiinQuant) - always set
        self._ingestion: IngestionService | None = None
        self._fill_failure_until: dict[str, float] = {}
        self._counters: dict[str, int] = {
            "db_hit_reads": 0,
            "db_partial_reads": 0,
            "provider_direct_reads": 0,
            "provider_calls_avoided": 0,
            "gap_fills_attempted": 0,
            "gap_fills_filled": 0,
            "gap_fills_failed": 0,
            "gap_fills_out_of_horizon": 0,
            "gap_fills_suppressed_cooldown": 0,
            "gap_fill_lock_timeouts": 0,
            "gap_fills_rejected_saturated": 0,
        }
        self._last_fill: dict | None = None

    # ------------------------------------------------------------------ #
    def set_provider(self, provider) -> None:
        """The direct provider (FiinQuant). Set unconditionally so provider-direct always works."""
        self._provider = provider

    def configure(
        self,
        *,
        engine: AsyncEngine,
        sessionmaker: async_sessionmaker[AsyncSession],
        provider,
        ingestion_service: IngestionService | None = None,
    ) -> None:
        self._engine = engine
        self._sm = sessionmaker
        self._provider = provider
        self._ingestion = ingestion_service or IngestionService(
            engine=engine, sessionmaker=sessionmaker, bar_provider=provider
        )

    def reset(self) -> None:
        self._engine = self._sm = self._ingestion = None
        self._fill_failure_until.clear()

    def ingestion_service(self) -> IngestionService | None:
        return self._ingestion

    # ------------------------------------------------------------------ #
    def _mode(self) -> str:
        m = (settings.HISTORY_SOURCE_MODE or "auto").strip().lower()
        if m == "provider_direct":
            return "provider_direct"
        if self._sm is None or self._ingestion is None:
            return "provider_direct"
        if m == "postgres_first":
            return "postgres_first"
        # auto
        return "postgres_first" if settings.DATABASE_ENABLED else "provider_direct"

    def read_mode(self) -> str:
        return self._mode()

    def _pg_timeframe(self, tf: str) -> bool:
        return tf in settings.history_postgres_timeframes()

    # ------------------------------------------------------------------ #
    async def get_history_readonly(
        self,
        symbol: str,
        *,
        timeframe: str,
        from_date: str | None,
        to_date: str | None,
        adjusted: bool,
    ) -> tuple[list[HistoricalBar], str]:
        """Strictly PostgreSQL-backed daily history: NO provider call, NO gap-fill, ever.

        Returns ``(bars, source)`` where ``source`` is one of ``"POSTGRES"`` (rows served
        from the persisted store, possibly a partial window) or ``"UNAVAILABLE"`` (the DB
        is not wired, the timeframe is not persisted, or the symbol is not seeded). This is
        the read path the AI research tool uses - it must never widen the server's upstream
        request surface on behalf of the model.
        """
        sym = symbol.strip().upper()
        tf = normalize_timeframe(timeframe)
        req_from, req_to = self._resolve_window(from_date, to_date, tf)

        if self._mode() != "postgres_first" or not self._pg_timeframe(tf):
            return [], "UNAVAILABLE"
        if self._sm is None:
            return [], "UNAVAILABLE"

        async with self._sm() as session:
            inst = await InstrumentRepository(session).get_by_symbol(sym)
        if inst is None:
            return [], "UNAVAILABLE"

        price_basis = "RAW" if inst.instrument_type == "CW" else ("ADJUSTED" if adjusted else "RAW")
        rows = await self._read_db(inst.id, tf, price_basis, req_from, req_to)
        return _to_wire(rows, price_basis), "POSTGRES"

    # ------------------------------------------------------------------ #
    # Today's session bar
    #
    # Neither source of completed bars can carry the current session: PostgreSQL only ever
    # holds sessions past their 15:00 close, and the provider's daily series stops at the
    # last completed session too. The chart used to paper over this with a bar assembled
    # from WebSocket ticks in the browser - which meant today's candle existed only in
    # whichever tab had been watching it stream. A reload after the close, or simply
    # opening on another machine, showed a chart whose newest candle was yesterday while
    # the header beside it quoted today's price.
    #
    # The live market state already holds the whole session's OHLCV server-side (restored
    # from Redis across restarts), so the honest fix is to serve it as the newest bar.
    # ------------------------------------------------------------------ #
    @staticmethod
    def _session_bar(
        symbol: str, req_from: date, req_to: date, *, adjusted: bool, price_basis: str
    ) -> HistoricalBar | None:
        """The current session as a daily bar, or None when it cannot be stated truthfully.

        Every field must be present and real. A partial session - an instrument that has
        quoted but not traded, a frame missing its session high - is a gap, not a bar to
        be part-invented, which is the same rule the provider path applies.
        """
        from app.market_data.market_state import market_state

        quote = market_state.get_quote(symbol)
        if quote is None or not quote.market_session_date:
            return None
        try:
            session_day = date.fromisoformat(quote.market_session_date[:10])
        except ValueError:
            return None
        if not (req_from <= session_day <= req_to):
            return None

        o, h, l = quote.open_price, quote.high_price, quote.low_price
        c, v = quote.last_price, quote.total_volume
        if any(x is None or x <= 0 for x in (o, h, l, c)) or v is None or v <= 0:
            return None

        return HistoricalBar(
            date=session_day.isoformat(),
            open=float(o), high=float(h), low=float(l), close=float(c),
            volume=float(v),
            value=float(quote.trading_value) if quote.trading_value is not None else None,
            # Corporate actions rescale bars BEFORE their ex-date, never the current one,
            # so the running session reads the same on either basis - this is the
            # requested basis, not a RAW bar smuggled into an ADJUSTED series.
            price_basis=price_basis,
            adjusted=adjusted,
            source="REALTIME_SESSION",
            session_date=session_day.isoformat(),
        )

    async def _observed_session_bars(
        self, symbol: str, req_from: date, req_to: date, *, adjusted: bool, price_basis: str
    ) -> list[HistoricalBar]:
        """Completed sessions the app observed itself, from the persisted snapshot store.

        The live-state bar alone was not enough. `market_state` is deliberately cleared at
        the 08:00 ICT rollover, so a session it was the only source for disappears from the
        chart the next morning - which is exactly what happened to 2026-09-07 once the
        market-data entitlement lapsed and the provider could no longer supply that day's
        completed bar either. The snapshot store still held it, dated and complete.

        Only whole bars are returned; a snapshot missing any OHLCV field is a gap.
        """
        if self._sm is None or not settings.SNAPSHOT_ENABLED:
            return []
        try:
            from app.persistence.repositories.snapshot_repository import SnapshotRepository

            async with self._sm() as session:
                rows = await SnapshotRepository(session).get_range(symbol, req_from, req_to)
        except Exception as err:  # noqa: BLE001 - the chart must not fail on a cache read
            logger.debug("history: snapshot range read failed for %s: %s", symbol, err)
            return []

        out: list[HistoricalBar] = []
        for r in rows:
            o, h, l = r.open_price, r.high_price, r.low_price
            c, v = r.last_price, r.total_volume
            if any(x is None or x <= 0 for x in (o, h, l, c)) or v is None or v <= 0:
                continue
            day = r.session_date.isoformat()
            out.append(HistoricalBar(
                date=day, open=float(o), high=float(h), low=float(l), close=float(c),
                volume=float(v),
                value=float(r.trading_value) if r.trading_value is not None else None,
                price_basis=price_basis, adjusted=adjusted,
                source="OBSERVED_SESSION", session_date=day,
            ))
        return out

    async def _with_session_bar(
        self, bars: list[HistoricalBar], symbol: str, tf: str,
        req_from: date, req_to: date, *, adjusted: bool, price_basis: str,
    ) -> list[HistoricalBar]:
        """Fill sessions the completed-bar sources do not carry.

        Two of them, in increasing authority: sessions the app observed and persisted, then
        the session running right now. A bar already in the series always wins over both -
        once a session is ingested, the exchange's own bar is the authority and these are
        only what this server happened to see.
        """
        if tf != "1d":
            return bars
        # Authority, highest first: an ingested bar (the exchange's own), then the running
        # session read live, then a persisted snapshot. Live outranks the snapshot for the
        # SAME day because a checkpoint is only the last thing written for a session that
        # is still moving.
        merged = {b.date[:10]: b for b in bars}
        live = self._session_bar(symbol, req_from, req_to, adjusted=adjusted, price_basis=price_basis)
        if live is not None:
            merged.setdefault(live.date, live)
        for observed in await self._observed_session_bars(
            symbol, req_from, req_to, adjusted=adjusted, price_basis=price_basis
        ):
            merged.setdefault(observed.date, observed)
        if len(merged) == len(bars):
            return bars
        return sorted(merged.values(), key=lambda b: b.date)

    # ------------------------------------------------------------------ #
    async def get_history(
        self,
        symbol: str,
        *,
        timeframe: str,
        from_date: str | None,
        to_date: str | None,
        adjusted: bool,
    ) -> list[HistoricalBar]:
        sym = symbol.strip().upper()
        tf = normalize_timeframe(timeframe)
        req_from, req_to = self._resolve_window(from_date, to_date, tf)

        if self._mode() != "postgres_first" or not self._pg_timeframe(tf):
            bars = await self._provider_direct(sym, timeframe, from_date, to_date, adjusted)
            return await self._with_session_bar(
                bars, sym, tf, req_from, req_to,
                adjusted=adjusted, price_basis="ADJUSTED" if adjusted else "RAW",
            )

        assert self._sm is not None and self._ingestion is not None
        async with self._sm() as session:
            inst = await InstrumentRepository(session).get_by_symbol(sym)
        if inst is None:
            logger.info("history: %s not in instruments; serving provider-direct", sym)
            bars = await self._provider_direct(sym, timeframe, from_date, to_date, adjusted)
            return await self._with_session_bar(
                bars, sym, tf, req_from, req_to,
                adjusted=adjusted, price_basis="ADJUSTED" if adjusted else "RAW",
            )

        price_basis = "RAW" if inst.instrument_type == "CW" else ("ADJUSTED" if adjusted else "RAW")
        rows = await self._read_db(inst.id, tf, price_basis, req_from, req_to)
        assessment = await self._assess(inst, tf, price_basis, req_from, req_to, rows)

        if assessment.covered or not settings.HISTORY_GAPFILL_ENABLED:
            self._counters["db_hit_reads" if assessment.covered else "db_partial_reads"] += 1
            self._counters["provider_calls_avoided"] += 1
            return await self._session_wrapped(rows, sym, tf, req_from, req_to, adjusted, price_basis)

        stream_key = f"{sym}:{tf}:{price_basis}"
        if self._in_cooldown(stream_key):
            self._counters["gap_fills_suppressed_cooldown"] += 1
            logger.info("history: %s gap-fill suppressed (recent failure cooldown); serving DB partial", stream_key)
            self._counters["db_partial_reads"] += 1
            return await self._session_wrapped(rows, sym, tf, req_from, req_to, adjusted, price_basis)

        # HTTP-layer global cap on how many DISTINCT streams may trigger a provider
        # gap-fill at once. This is SEPARATE from ingestion's own request throttling /
        # per-stream advisory lock - it just stops a burst of many-symbol cache misses
        # from each occupying a worker on an upstream call. Saturated -> serve the DB
        # partial now (graceful), never queue.
        from app.security.concurrency import GateTimeout, history_gapfill_gate

        self._counters["gap_fills_attempted"] += 1
        try:
            # Wait for a slot up to the same budget a concurrent miss already spends waiting
            # on the per-stream advisory lock; a genuine flood beyond that serves the DB
            # partial rather than piling upstream calls.
            async with history_gapfill_gate.acquire(
                timeout=float(settings.HISTORY_GAPFILL_LOCK_WAIT_SECONDS)
            ):
                outcome = await self._ingestion.fill_range(
                    sym, timeframe=tf, price_basis=price_basis,
                    from_date=assessment.fill_from or req_from, to_date=assessment.fill_to or req_to,
                )
            self._record_fill(stream_key, outcome)
        except GateTimeout:
            self._counters["gap_fills_rejected_saturated"] += 1
            self._counters["db_partial_reads"] += 1
            logger.info(
                "history: %s gap-fill deferred (global concurrency cap %d reached); serving DB partial",
                stream_key, settings.HISTORY_MAX_CONCURRENT_GAPFILLS,
            )
            return await self._session_wrapped(rows, sym, tf, req_from, req_to, adjusted, price_basis)

        rows = await self._read_db(inst.id, tf, price_basis, req_from, req_to)
        return await self._session_wrapped(rows, sym, tf, req_from, req_to, adjusted, price_basis)

    # ------------------------------------------------------------------ #
    async def _session_wrapped(self, rows, sym, tf, req_from, req_to, adjusted, price_basis):
        return await self._with_session_bar(
            _to_wire(rows, price_basis), sym, tf, req_from, req_to,
            adjusted=adjusted, price_basis=price_basis,
        )

    def _direct_provider(self):
        if self._provider is not None:
            return self._provider
        # Fallback for contexts where the lifespan has not wired us (e.g. TestClient used
        # without a context manager): the live subscription manager owns the provider.
        from app.market_data.market_subscription_manager import subscription_manager

        return subscription_manager.provider

    async def _provider_direct(self, sym, timeframe, from_date, to_date, adjusted):
        self._counters["provider_direct_reads"] += 1
        return await self._direct_provider().get_historical_bars(
            symbol=sym, timeframe=timeframe, from_date=from_date, to_date=to_date, adjusted=adjusted
        )

    async def _read_db(self, instrument_id: int, tf: str, price_basis: str, req_from: date, req_to: date):
        assert self._sm is not None
        start = datetime.combine(req_from, datetime.min.time(), tzinfo=VN_TZ)
        end = datetime.combine(req_to + timedelta(days=1), datetime.min.time(), tzinfo=VN_TZ)
        async with self._sm() as session:
            return await MarketBarRepository(session).get_bars(
                instrument_id=instrument_id, timeframe=tf, price_basis=price_basis,
                start=start, end=end, ascending=True, limit=settings.HISTORY_MAX_RESULT_BARS,
            )

    async def _assess(self, inst, tf: str, price_basis: str, req_from: date, req_to: date, rows) -> _CoverageAssessment:
        assert self._ingestion is not None
        cutoff = last_completed_session_date()
        win_lo, win_hi = req_from, min(req_to, cutoff)
        if inst.first_trade_date and inst.first_trade_date > win_lo:
            win_lo = inst.first_trade_date          # test D: absence before listing is not a gap
        if inst.last_trade_date and inst.last_trade_date < win_hi:
            win_hi = inst.last_trade_date            # test E: no fill beyond a CW's trading life
        if win_lo > win_hi:
            return _CoverageAssessment(True, None, None, "nothing legitimately expected in window")

        present = {r.session_date for r in rows}
        expected = expected_trading_days(win_lo, win_hi)
        missing = [d for d in expected if d not in present]
        if not missing:
            return _CoverageAssessment(True, None, None, "all expected sessions present")

        # Which missing days have we already probed the provider for? (cursor = ingestion_state)
        state = await self._ingestion.get_stream_state(
            instrument_id=inst.id, timeframe=tf, price_basis=price_basis
        )
        cur_lo = state.backfilled_from_ts.astimezone(VN_TZ).date() if state and state.backfilled_from_ts else None
        cur_hi = state.last_bar_ts.astimezone(VN_TZ).date() if state and state.last_bar_ts else None

        horizon_floor = date.today() - timedelta(days=settings.INGEST_MAX_LOOKBACK_DAYS)
        # A day this recent is always retried regardless of the cursor - see the docstring
        # on HISTORY_RECENT_RETRY_DAYS for why "the cursor already spans it" is not reliable
        # evidence of a confirmed gap this close to today (confirmed live: an EOD-analytics
        # gap-fill for VPB/FPT's ADJUSTED series kept reporting "FILLED" with zero rows
        # inserted for the current session's close, hours after FiinQuant actually published
        # it, because an earlier fill's `requested_ceiling` had already stamped the cursor
        # past that date the moment it was first (unsuccessfully) asked for).
        recent_floor = date.today() - timedelta(days=settings.HISTORY_RECENT_RETRY_DAYS)

        def _probed(d: date) -> bool:
            if d >= recent_floor:
                return False
            # The provider has already been asked for this date at least once (cursor spans it).
            return cur_lo is not None and cur_hi is not None and cur_lo <= d <= cur_hi

        # A chart read fills a missing day only when ALL of:
        #   * inside the provider's accessible horizon (never probe forbidden history),
        #   * never probed before (a probed-but-empty day is a confirmed non-trading day -
        #     re-fetching it on every chart load is the exact anti-pattern to avoid),
        #   * not inside the approximate Lunar-New-Year closure window (a known ~week gap;
        #     the operator `repair --include-unknown` can still force it).
        # Weekends and fixed public holidays are already excluded from `expected`.
        fillable = [
            d for d in missing
            if d >= horizon_floor and not _probed(d) and not in_tet_window(d)
        ]
        if not fillable:
            return _CoverageAssessment(
                True, None, None,
                "only expected-non-trading / already-probed / out-of-horizon gaps remain",
                missing_sessions=len(missing),
            )
        # Tight window: from the earliest fillable missing day to the latest. `fill_range`
        # then chunks + resume-skips so only the genuinely un-covered portion is fetched.
        return _CoverageAssessment(
            False, min(fillable), max(fillable),
            f"{len(fillable)}/{len(missing)} missing session(s) fillable inside the horizon",
            missing_sessions=len(missing),
        )

    # ------------------------------------------------------------------ #
    def _in_cooldown(self, stream_key: str) -> bool:
        until = self._fill_failure_until.get(stream_key)
        return until is not None and time.monotonic() < until

    def _record_fill(self, stream_key: str, outcome: GapFillOutcome) -> None:
        self._last_fill = {
            "stream": stream_key, "status": outcome.status, "rows_inserted": outcome.rows_inserted,
            "rows_updated": outcome.rows_updated, "provider_calls": outcome.provider_calls,
            "error_class": outcome.error_class, "at": datetime.now(VN_TZ).isoformat(),
        }
        if outcome.status == "FILLED":
            self._counters["gap_fills_filled"] += 1
            self._fill_failure_until.pop(stream_key, None)
        elif outcome.status == "OUT_OF_HORIZON":
            self._counters["gap_fills_out_of_horizon"] += 1
        elif outcome.status == "LOCK_TIMEOUT":
            self._counters["gap_fill_lock_timeouts"] += 1
        elif outcome.status == "ALREADY_COVERED":
            self._counters["provider_calls_avoided"] += 1
        else:  # PROVIDER_FAILED / NO_INSTRUMENT
            self._counters["gap_fills_failed"] += 1
            self._fill_failure_until[stream_key] = (
                time.monotonic() + float(settings.HISTORY_GAPFILL_FAILURE_COOLDOWN_SECONDS)
            )

    # ------------------------------------------------------------------ #
    def _resolve_window(self, from_date: str | None, to_date: str | None, tf: str) -> tuple[date, date]:
        today = date.today()
        d_to = _parse_date(to_date, "to_date") if to_date else today
        d_from = (
            _parse_date(from_date, "from_date") if from_date
            else d_to - timedelta(days=settings.HISTORY_DEFAULT_LOOKBACK_DAYS)
        )
        if d_from > d_to:
            raise HistoryRequestError(f"from_date {d_from} is after to_date {d_to}")
        span = (d_to - d_from).days
        if span > settings.HISTORY_MAX_RANGE_DAYS:
            raise HistoryRequestError(
                f"requested span {span} days exceeds the maximum {settings.HISTORY_MAX_RANGE_DAYS} "
                f"days per request"
            )
        return d_from, d_to

    # ------------------------------------------------------------------ #
    def health(self) -> dict:
        return {
            "read_mode": self._mode(),
            "database_wired": self._sm is not None,
            "gapfill_enabled": bool(settings.HISTORY_GAPFILL_ENABLED),
            "streams_in_failure_cooldown": sum(
                1 for u in self._fill_failure_until.values() if time.monotonic() < u
            ),
            "last_gap_fill": self._last_fill,
            "counters": dict(self._counters),
        }


def _parse_date(value: str, field_name: str) -> date:
    try:
        return datetime.strptime(value.strip()[:10], "%Y-%m-%d").date()
    except (ValueError, AttributeError) as exc:
        raise HistoryRequestError(f"{field_name} must be YYYY-MM-DD, got {value!r}") from exc


def _to_wire(rows, price_basis: str) -> list[HistoricalBar]:
    is_adj = price_basis == "ADJUSTED"
    return [
        HistoricalBar(
            date=r.session_date.isoformat(),
            open=r.open, high=r.high, low=r.low, close=r.close,
            volume=float(r.volume), adjusted=is_adj,
            value=r.trading_value,
            price_basis=price_basis,
            session_date=r.session_date.isoformat(),
        )
        for r in rows
    ]


history_read_service = HistoryReadService()
