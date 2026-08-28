"""IngestionService - resumable, quota-safe historical backfill + incremental sync.

Ties together: a ``HistoricalBarProvider`` (FiinQuant, or another legitimate source later),
the Step-5 repositories, chunk planning, retry, throttling and PostgreSQL advisory locks.

Durable unit of work = **one logical stream + one provider chunk**, committed in one
transaction (bars upsert + ``ingestion_state`` cursor). A later failure never rolls back an
earlier committed chunk. ``ingestion_state`` is a cursor/optimization; persisted
``market_bars`` remain authoritative and are reconciled against on resume.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import settings
from app.market_data.market_schemas import HistoricalBar, HistoricalDataError
from app.persistence.ingestion.chunking import BackfillPlan, generate_chunks, plan_backfill_windows
from app.persistence.ingestion.locks import stream_lock
from app.persistence.ingestion.mapping import map_history
from app.persistence.ingestion.retry import RetryPolicy, call_with_retry, classify, is_retryable
from app.persistence.ingestion.trading_calendar import last_completed_session_date
from app.persistence.market_time import VN_TZ, normalize_price_basis, normalize_timeframe
from app.persistence.repositories.ingestion_repository import IngestionRepository
from app.persistence.repositories.instrument_repository import InstrumentRepository, InstrumentUpsert
from app.persistence.repositories.market_bar_repository import MarketBarRepository

logger = logging.getLogger(__name__)

_CW_RE = re.compile(r"^C[A-Z]{2,4}\d{4}$")


class HistoricalBarProvider(Protocol):
    async def get_historical_bars(
        self,
        symbol: str,
        timeframe: str = "1D",
        from_date: str | None = None,
        to_date: str | None = None,
        adjusted: bool = True,
    ) -> list[HistoricalBar]: ...


class InvalidRequestError(ValueError):
    """Bad symbol / price-basis / timeframe combination - fail fast, never hit the provider."""


class _Throttle:
    """Global minimum interval between successive provider requests (all workers share it)."""

    def __init__(self, min_interval: float) -> None:
        self._min = max(0.0, min_interval)
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def wait(self) -> None:
        if self._min <= 0:
            return
        async with self._lock:
            delta = time.monotonic() - self._last
            if delta < self._min:
                await asyncio.sleep(self._min - delta)
            self._last = time.monotonic()


# --------------------------------------------------------------------------- #
# Result types
# --------------------------------------------------------------------------- #
@dataclass
class ChunkOutcome:
    seq: int
    start: str
    end: str
    status: str                    # SUCCEEDED | SKIPPED_COVERED | FAILED | PLANNED
    fetched: int = 0
    inserted: int = 0
    updated: int = 0
    dropped_incomplete: int = 0
    attempts: int = 0
    error: str | None = None


@dataclass
class StreamOutcome:
    symbol: str
    instrument_id: int | None
    instrument_type: str | None
    timeframe: str
    price_basis: str
    status: str                    # SUCCEEDED | PARTIAL | FAILED | LOCKED_SKIPPED | DRY_RUN
    lookback_clamped: bool = False
    clamp_note: str | None = None
    chunks: list[ChunkOutcome] = field(default_factory=list)
    error: str | None = None

    def _sum(self, attr: str) -> int:
        return sum(getattr(c, attr) for c in self.chunks)

    @property
    def fetched(self) -> int:
        return self._sum("fetched")

    @property
    def inserted(self) -> int:
        return self._sum("inserted")

    @property
    def updated(self) -> int:
        return self._sum("updated")


@dataclass
class IngestionResult:
    run_id: int | None
    operation: str
    timeframe: str
    price_basis: str
    dry_run: bool
    streams: list[StreamOutcome] = field(default_factory=list)

    def totals(self) -> tuple[int, int, int]:
        return (
            sum(s.fetched for s in self.streams),
            sum(s.inserted for s in self.streams),
            sum(s.updated for s in self.streams),
        )

    @property
    def status(self) -> str:
        if self.dry_run:
            return "DRY_RUN"
        states = {s.status for s in self.streams}
        if states <= {"SUCCEEDED", "LOCKED_SKIPPED"}:
            return "SUCCEEDED" if "SUCCEEDED" in states else "LOCKED_SKIPPED"
        if states & {"SUCCEEDED", "PARTIAL"}:
            return "PARTIAL"
        return "FAILED"


# --------------------------------------------------------------------------- #
class IngestionService:
    def __init__(
        self,
        *,
        engine: AsyncEngine,
        sessionmaker: async_sessionmaker[AsyncSession],
        bar_provider: HistoricalBarProvider,
        source: str | None = None,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self._engine = engine
        self._sm = sessionmaker
        self._provider = bar_provider
        self._source = source or settings.INGEST_SOURCE_LABEL
        self._retry = retry_policy or RetryPolicy.from_settings()
        self._throttle = _Throttle(float(settings.INGEST_MIN_REQUEST_INTERVAL_SECONDS))

    # ---- validation helpers ---------------------------------------- #
    @staticmethod
    def _looks_like_cw(symbol: str) -> bool:
        return bool(_CW_RE.match(symbol.strip().upper()))

    def _price_basis_for(self, symbol: str, instrument_type: str | None, adjusted: bool) -> str:
        itype = (instrument_type or ("CW" if self._looks_like_cw(symbol) else "STOCK")).upper()
        if itype == "CW" and adjusted:
            raise InvalidRequestError(
                f"{symbol}: covered warrants have no corporate-action-adjusted upstream series; "
                f"pass RAW (--raw). Refusing to persist CW bars falsely labelled ADJUSTED."
            )
        return normalize_price_basis(adjusted=adjusted)

    def _clean_symbols(self, symbols: list[str]) -> list[str]:
        clean = list(dict.fromkeys(s.strip().upper() for s in symbols if s.strip()))
        if not clean:
            raise InvalidRequestError("no symbols given")
        if len(clean) > settings.INGEST_MAX_SYMBOLS_PER_INVOCATION:
            raise InvalidRequestError(
                f"{len(clean)} symbols exceeds INGEST_MAX_SYMBOLS_PER_INVOCATION="
                f"{settings.INGEST_MAX_SYMBOLS_PER_INVOCATION}; split the invocation"
            )
        return clean

    # ---- instrument resolution ----------------------------------- #
    async def _lookup_instrument(self, symbol: str) -> tuple[int | None, str | None]:
        async with self._sm() as session:
            row = await InstrumentRepository(session).get_by_symbol(symbol)
        return (row.id, row.instrument_type) if row else (None, None)

    async def _ensure_instrument(self, symbol: str) -> tuple[int, str]:
        async with self._sm() as session, session.begin():
            repo = InstrumentRepository(session)
            row = await repo.get_by_symbol(symbol)
            if row is not None:
                return row.id, row.instrument_type
            itype = "CW" if self._looks_like_cw(symbol) else "STOCK"
            logger.warning("%s absent from instruments; creating minimal %s row", symbol, itype)
            created = await repo.upsert(
                InstrumentUpsert(symbol=symbol, instrument_type=itype, metadata={"autocreated_by": "ingestion"})
            )
            return created.id, created.instrument_type

    # ---- plan a single stream ----------------------------------- #
    async def _plan_stream(
        self, *, operation: str, instrument_id: int | None, tf: str, price_basis: str,
        from_date: date | None, to_date: date | None, force: bool,
    ) -> BackfillPlan:
        today = date.today()
        if operation == "backfill":
            assert from_date is not None and to_date is not None
            plan = plan_backfill_windows(from_date, to_date, today=today)
            if force or plan.is_empty or instrument_id is None:
                return plan
            state = await self._get_state(instrument_id, tf, price_basis)
            if state is None or state.last_bar_ts is None:
                return plan
            # Resume-skip a chunk only when it is covered on BOTH ends: its whole span sits
            # inside [backfilled_from, last_bar] already persisted. Skipping on the forward
            # cursor alone would silently drop a chunk when a later backfill requests an
            # EARLIER --from than the current coverage (backward extension).
            covered_lo = (
                state.backfilled_from_ts.astimezone(VN_TZ).date()
                if state.backfilled_from_ts is not None
                else date.max
            )
            covered_hi = state.last_bar_ts.astimezone(VN_TZ).date()
            remaining = tuple(
                c for c in plan.chunks if not (c.start >= covered_lo and c.end <= covered_hi)
            )
            return _replace_chunks(plan, remaining)

        # incremental: window derived from persisted coverage + a timeframe safety overlap
        overlap = (
            settings.INGEST_INCREMENTAL_OVERLAP_DAYS_1D if tf == "1d"
            else settings.INGEST_INCREMENTAL_OVERLAP_DAYS_INTRADAY
        )
        horizon_start = today - timedelta(days=settings.INGEST_MAX_LOOKBACK_DAYS)
        cutoff = last_completed_session_date()
        latest = None
        if instrument_id is not None:
            async with self._sm() as session:
                cov = await MarketBarRepository(session).coverage(
                    instrument_id=instrument_id, timeframe=tf, price_basis=price_basis
                )
            latest = cov.latest_ts
        start = horizon_start if latest is None else (latest.astimezone(VN_TZ).date() - timedelta(days=overlap))
        start = max(start, horizon_start)
        if start > cutoff:
            return BackfillPlan(today, cutoff, start, cutoff, (), False, "already current")
        chunks = tuple(generate_chunks(start, cutoff, max_span_days=settings.INGEST_MAX_CHUNK_SPAN_DAYS))
        return BackfillPlan(start, cutoff, start, cutoff, chunks, False, None)

    async def _get_state(self, instrument_id: int, tf: str, price_basis: str):
        async with self._sm() as session:
            return await IngestionRepository(session).get_state(
                source=self._source, instrument_id=instrument_id, timeframe=tf, price_basis=price_basis
            )

    # ---- fetch one chunk with retry + throttle ------------------ #
    async def _fetch_chunk(self, symbol: str, tf: str, f_iso: str, t_iso: str, adjusted: bool):
        await self._throttle.wait()

        async def _do() -> list[HistoricalBar]:
            return await self._provider.get_historical_bars(
                symbol=symbol, timeframe=tf, from_date=f_iso, to_date=t_iso, adjusted=adjusted
            )

        return await call_with_retry(_do, policy=self._retry, label=f"{symbol} {tf} {f_iso}..{t_iso}")

    # ---- public operations ------------------------------------- #
    async def backfill(
        self, symbols: list[str], *, timeframe: str, adjusted: bool, from_date: date, to_date: date,
        concurrency: int | None = None, dry_run: bool = False, force: bool = False,
        include_forming: bool = False,
    ) -> IngestionResult:
        return await self._drive(
            "backfill", symbols, timeframe=timeframe, adjusted=adjusted, from_date=from_date,
            to_date=to_date, concurrency=concurrency, dry_run=dry_run, force=force,
            include_forming=include_forming,
        )

    async def incremental(
        self, symbols: list[str], *, timeframe: str, adjusted: bool,
        concurrency: int | None = None, dry_run: bool = False, include_forming: bool = False,
    ) -> IngestionResult:
        return await self._drive(
            "incremental", symbols, timeframe=timeframe, adjusted=adjusted, from_date=None,
            to_date=None, concurrency=concurrency, dry_run=dry_run, force=False,
            include_forming=include_forming,
        )

    async def _drive(
        self, operation: str, symbols: list[str], *, timeframe: str, adjusted: bool,
        from_date: date | None, to_date: date | None, concurrency: int | None,
        dry_run: bool, force: bool, include_forming: bool,
    ) -> IngestionResult:
        tf = normalize_timeframe(timeframe)
        clean = self._clean_symbols(symbols)
        price_basis = normalize_price_basis(adjusted=adjusted)
        conc = max(1, int(concurrency or settings.INGEST_MAX_CONCURRENT_REQUESTS))
        result = IngestionResult(None, operation, tf, price_basis, dry_run)

        run_id: int | None = None
        if not dry_run:
            async with self._sm() as session, session.begin():
                run = await IngestionRepository(session).start_run(
                    source=self._source, timeframe=tf, price_basis=price_basis, requested_symbols=clean,
                    requested_from=_dt(from_date), requested_to=_dt(to_date),
                )
                run_id = run.id
            result.run_id = run_id

        sem = asyncio.Semaphore(conc)

        async def worker(sym: str) -> StreamOutcome:
            async with sem:
                try:
                    return await self._one_stream(
                        symbol=sym, tf=tf, adjusted=adjusted, operation=operation, from_date=from_date,
                        to_date=to_date, run_id=run_id, dry_run=dry_run, force=force,
                        include_forming=include_forming,
                    )
                except InvalidRequestError as exc:
                    return StreamOutcome(sym, None, None, tf, price_basis, "FAILED", error=str(exc))

        try:
            result.streams = list(await asyncio.gather(*(worker(s) for s in clean)))
        finally:
            if not dry_run and run_id is not None:
                await self._finalize_run(run_id, result)
        return result

    async def _one_stream(
        self, *, symbol: str, tf: str, adjusted: bool, operation: str, from_date: date | None,
        to_date: date | None, run_id: int | None, dry_run: bool, force: bool, include_forming: bool,
    ) -> StreamOutcome:
        if dry_run:
            instrument_id, instrument_type = await self._lookup_instrument(symbol)
        else:
            instrument_id, instrument_type = await self._ensure_instrument(symbol)

        price_basis = self._price_basis_for(symbol, instrument_type, adjusted)
        outcome = StreamOutcome(symbol, instrument_id, instrument_type, tf, price_basis, "SUCCEEDED")

        plan = await self._plan_stream(
            operation=operation, instrument_id=instrument_id, tf=tf, price_basis=price_basis,
            from_date=from_date, to_date=to_date, force=(force or dry_run),
        )
        outcome.lookback_clamped = plan.lookback_clamped
        outcome.clamp_note = plan.clamp_note

        if plan.is_empty:
            outcome.status = "DRY_RUN" if dry_run else ("PARTIAL" if plan.lookback_clamped else "SUCCEEDED")
            return outcome

        if dry_run:
            outcome.chunks = [
                ChunkOutcome(c.seq, c.start.isoformat(), c.end.isoformat(), "PLANNED") for c in plan.chunks
            ]
            outcome.status = "DRY_RUN"
            return outcome

        assert instrument_id is not None
        async with stream_lock(
            self._engine, source=self._source, instrument_id=instrument_id, timeframe=tf,
            price_basis=price_basis, wait=False,
        ) as acquired:
            if not acquired:
                outcome.status = "LOCKED_SKIPPED"
                return outcome
            await self._run_chunks(
                outcome=outcome, symbol=symbol, tf=tf, adjusted=adjusted, price_basis=price_basis,
                instrument_id=instrument_id, plan=plan, run_id=run_id, include_forming=include_forming,
            )
        return outcome

    async def _run_chunks(
        self, *, outcome: StreamOutcome, symbol: str, tf: str, adjusted: bool, price_basis: str,
        instrument_id: int, plan: BackfillPlan, run_id: int | None, include_forming: bool,
    ) -> None:
        any_ok = any_fail = False
        # oldest window boundary we have deliberately requested this run - persisted as
        # ingestion_state.backfilled_from_ts so a resume knows the range is covered even
        # when the requested start precedes the first actual trading day (holiday/weekend).
        requested_floor = min(
            (datetime(c.start.year, c.start.month, c.start.day, tzinfo=timezone.utc) for c in plan.chunks),
            default=None,
        )
        for chunk in plan.chunks:
            co = ChunkOutcome(chunk.seq, chunk.start.isoformat(), chunk.end.isoformat(), "FAILED")
            outcome.chunks.append(co)
            try:
                bars, attempts = await self._fetch_chunk(symbol, tf, *chunk.as_iso(), adjusted)
                co.attempts, co.fetched = attempts, len(bars)
                mapped = map_history(
                    bars, instrument_id=instrument_id, timeframe=tf, price_basis=price_basis,
                    source=self._source, include_forming=include_forming,
                )
                co.dropped_incomplete = mapped.dropped_incomplete

                async with self._sm() as session, session.begin():
                    bar_repo = MarketBarRepository(session)
                    if mapped.rows:
                        res = await bar_repo.bulk_upsert_bars(mapped.rows, ingestion_run_id=run_id)
                        co.inserted, co.updated = res.inserted, res.updated
                    cov = await bar_repo.coverage(
                        instrument_id=instrument_id, timeframe=tf, price_basis=price_basis
                    )
                    floor_candidates = [
                        ts for ts in (cov.earliest_ts, mapped.min_ts, requested_floor) if ts is not None
                    ]
                    ing_repo = IngestionRepository(session)
                    await ing_repo.upsert_state(
                        source=self._source, instrument_id=instrument_id, timeframe=tf, price_basis=price_basis,
                        last_bar_ts=cov.latest_ts or mapped.max_ts,
                        backfilled_from_ts=min(floor_candidates) if floor_candidates else None,
                        last_success_at=datetime.now(timezone.utc), last_run_id=run_id,
                    )
                    if run_id is not None:
                        await ing_repo.add_progress(
                            run_id, rows_fetched=co.fetched, rows_inserted=co.inserted,
                            rows_updated=co.updated,
                        )
                co.status = "SUCCEEDED"
                any_ok = True
            except HistoricalDataError as exc:
                co.error = f"{classify(exc)}: {exc}"
                any_fail = True
                if not is_retryable(exc):
                    logger.error("%s %s: non-retryable %s - halting stream", symbol, tf, classify(exc))
                    outcome.error = co.error
                    break
            except Exception as exc:  # noqa: BLE001
                co.error = f"UNEXPECTED {exc.__class__.__name__}: {exc}"
                any_fail = True
                logger.exception("%s %s chunk %d unexpected error", symbol, tf, chunk.seq)

        if plan.lookback_clamped or (any_fail and any_ok):
            outcome.status = "PARTIAL"
        elif any_fail:
            outcome.status = "FAILED"
        else:
            outcome.status = "SUCCEEDED"

    # ---- run bookkeeping -------------------------------------- #
    async def _finalize_run(self, run_id: int, result: IngestionResult) -> None:
        fetched, inserted, updated = result.totals()
        states = {s.status for s in result.streams}
        if states <= {"SUCCEEDED", "LOCKED_SKIPPED"}:
            status = "SUCCEEDED"
        elif states & {"SUCCEEDED", "PARTIAL"} or any(s.lookback_clamped for s in result.streams):
            status = "PARTIAL"
        else:
            status = "FAILED"
        notes = "; ".join(
            f"{s.symbol}: {s.error or s.clamp_note}"
            for s in result.streams if s.error or s.clamp_note
        )
        try:
            async with self._sm() as session, session.begin():
                await IngestionRepository(session).complete_run(
                    run_id, status=status, rows_fetched=fetched, rows_inserted=inserted,
                    rows_updated=updated, error_summary=(notes[:1990] or None),
                )
        except Exception:  # noqa: BLE001
            logger.exception("failed to finalise ingestion_run %d", run_id)

    # ---- status --------------------------------------------- #
    async def status(self, symbols: list[str], *, timeframe: str, adjusted: bool) -> list[dict]:
        tf = normalize_timeframe(timeframe)
        pb = normalize_price_basis(adjusted=adjusted)
        out: list[dict] = []
        async with self._sm() as session:
            irepo, brepo, grepo = (
                InstrumentRepository(session), MarketBarRepository(session), IngestionRepository(session)
            )
            for sym in (s.strip().upper() for s in symbols if s.strip()):
                inst = await irepo.get_by_symbol(sym)
                if inst is None:
                    out.append({"symbol": sym, "seeded": False})
                    continue
                cov = await brepo.coverage(instrument_id=inst.id, timeframe=tf, price_basis=pb)
                state = await grepo.get_state(
                    source=self._source, instrument_id=inst.id, timeframe=tf, price_basis=pb
                )
                out.append({
                    "symbol": sym, "seeded": True, "instrument_type": inst.instrument_type,
                    "timeframe": tf, "price_basis": pb, "bar_count": cov.bar_count,
                    "earliest": cov.earliest_ts.isoformat() if cov.earliest_ts else None,
                    "latest": cov.latest_ts.isoformat() if cov.latest_ts else None,
                    "cursor_last_bar_ts": (
                        state.last_bar_ts.isoformat() if state and state.last_bar_ts else None
                    ),
                    "cursor_last_success_at": (
                        state.last_success_at.isoformat() if state and state.last_success_at else None
                    ),
                })
        return out


def _dt(d: date | None) -> datetime | None:
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc) if d else None


def _replace_chunks(plan: BackfillPlan, chunks) -> BackfillPlan:
    return BackfillPlan(
        requested_start=plan.requested_start, requested_end=plan.requested_end,
        effective_start=plan.effective_start, effective_end=plan.effective_end,
        chunks=tuple(chunks), lookback_clamped=plan.lookback_clamped, clamp_note=plan.clamp_note,
    )
