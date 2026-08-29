"""Data access for ``ingestion_runs`` (job observability) and ``ingestion_state`` (sync cursor)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.persistence.market_time import normalize_timeframe, require_aware_utc
from app.persistence.models import IngestionRun, IngestionState
from app.persistence.rows import IngestionRunRow, IngestionStateRow

_RUN_STATUSES = {"RUNNING", "SUCCEEDED", "FAILED", "PARTIAL"}


def _run_row(m: IngestionRun) -> IngestionRunRow:
    return IngestionRunRow(
        id=m.id,
        source=m.source,
        timeframe=m.timeframe,
        price_basis=m.price_basis,
        requested_symbols=list(m.requested_symbols or []),
        requested_from=m.requested_from,
        requested_to=m.requested_to,
        status=m.status,
        started_at=m.started_at,
        completed_at=m.completed_at,
        rows_fetched=m.rows_fetched,
        rows_inserted=m.rows_inserted,
        rows_updated=m.rows_updated,
        error_summary=m.error_summary,
    )


def _state_row(m: IngestionState) -> IngestionStateRow:
    return IngestionStateRow(
        id=m.id,
        source=m.source,
        instrument_id=m.instrument_id,
        timeframe=m.timeframe,
        price_basis=m.price_basis,
        last_bar_ts=m.last_bar_ts,
        backfilled_from_ts=m.backfilled_from_ts,
        last_success_at=m.last_success_at,
        last_run_id=m.last_run_id,
        updated_at=m.updated_at,
    )


def _norm_basis(price_basis: str) -> str:
    pb = price_basis.strip().upper()
    if pb not in ("ADJUSTED", "RAW"):
        raise ValueError(f"price_basis must be ADJUSTED or RAW, got {price_basis!r}")
    return pb


class IngestionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ---- ingestion_runs -------------------------------------------------- #
    async def start_run(
        self,
        *,
        source: str,
        timeframe: str,
        price_basis: str,
        requested_symbols: list[str],
        requested_from: datetime | None = None,
        requested_to: datetime | None = None,
    ) -> IngestionRunRow:
        m = IngestionRun(
            source=source.strip(),
            timeframe=normalize_timeframe(timeframe),
            price_basis=_norm_basis(price_basis),
            requested_symbols=[s.strip().upper() for s in requested_symbols],
            requested_from=require_aware_utc(requested_from, field="requested_from") if requested_from else None,
            requested_to=require_aware_utc(requested_to, field="requested_to") if requested_to else None,
            status="RUNNING",
        )
        self._session.add(m)
        await self._session.flush()
        return _run_row(m)

    async def complete_run(
        self,
        run_id: int,
        *,
        status: str,
        rows_fetched: int = 0,
        rows_inserted: int = 0,
        rows_updated: int = 0,
        error_summary: str | None = None,
    ) -> IngestionRunRow:
        st = status.strip().upper()
        if st not in _RUN_STATUSES or st == "RUNNING":
            raise ValueError(f"completion status must be one of SUCCEEDED/FAILED/PARTIAL, got {status!r}")
        m = await self._session.get(IngestionRun, run_id)
        if m is None:
            raise LookupError(f"ingestion_run {run_id} does not exist")
        m.status = st
        m.rows_fetched = int(rows_fetched)
        m.rows_inserted = int(rows_inserted)
        m.rows_updated = int(rows_updated)
        m.error_summary = error_summary
        m.completed_at = datetime.now(timezone.utc)
        m.updated_at = datetime.now(timezone.utc)
        await self._session.flush()
        return _run_row(m)

    async def add_progress(
        self,
        run_id: int,
        *,
        rows_fetched: int = 0,
        rows_inserted: int = 0,
        rows_updated: int = 0,
    ) -> None:
        """Atomically INCREMENT a still-RUNNING run's counters (concurrency-safe: each
        caller reports only its own delta). No-op once the run is completed."""
        await self._session.execute(
            update(IngestionRun)
            .where(IngestionRun.id == run_id, IngestionRun.status == "RUNNING")
            .values(
                rows_fetched=IngestionRun.rows_fetched + int(rows_fetched),
                rows_inserted=IngestionRun.rows_inserted + int(rows_inserted),
                rows_updated=IngestionRun.rows_updated + int(rows_updated),
                updated_at=datetime.now(timezone.utc),
            )
        )

    async def fail_orphaned_runs(self, *, older_than_minutes: int = 30) -> int:
        """Mark ``RUNNING`` runs that started more than ``older_than_minutes`` ago as
        ``FAILED``. A run is only ever ``RUNNING`` while a live in-process task owns it, so
        an old ``RUNNING`` row means the process died / was cancelled mid-run (e.g. a
        deploy, or the HV warm-up timeout cancelling an in-flight gap-fill). The persisted
        ``market_bars`` are unaffected - they are committed per chunk, independent of the
        run row. Returns the number of rows corrected.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=max(1, int(older_than_minutes)))
        res = await self._session.execute(
            update(IngestionRun)
            .where(IngestionRun.status == "RUNNING", IngestionRun.started_at < cutoff)
            .values(
                status="FAILED",
                completed_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
                error_summary="orphaned: process exited or run was cancelled while RUNNING",
            )
        )
        return int(getattr(res, "rowcount", 0) or 0)

    async def get_run(self, run_id: int) -> IngestionRunRow | None:
        m = await self._session.get(IngestionRun, run_id)
        return _run_row(m) if m is not None else None

    async def recent_runs(self, limit: int = 20) -> list[IngestionRunRow]:
        stmt = select(IngestionRun).order_by(IngestionRun.started_at.desc()).limit(int(limit))
        return [_run_row(m) for m in (await self._session.execute(stmt)).scalars().all()]

    # ---- ingestion_state ----------------------------------------------- #
    async def get_state(
        self, *, source: str, instrument_id: int, timeframe: str, price_basis: str
    ) -> IngestionStateRow | None:
        stmt = select(IngestionState).where(
            IngestionState.source == source.strip(),
            IngestionState.instrument_id == instrument_id,
            IngestionState.timeframe == normalize_timeframe(timeframe),
            IngestionState.price_basis == _norm_basis(price_basis),
        )
        m = (await self._session.execute(stmt)).scalar_one_or_none()
        return _state_row(m) if m is not None else None

    async def upsert_state(
        self,
        *,
        source: str,
        instrument_id: int,
        timeframe: str,
        price_basis: str,
        last_bar_ts: datetime | None = None,
        backfilled_from_ts: datetime | None = None,
        last_success_at: datetime | None = None,
        last_run_id: int | None = None,
    ) -> IngestionStateRow:
        tf = normalize_timeframe(timeframe)
        pb = _norm_basis(price_basis)
        values = {
            "source": source.strip(),
            "instrument_id": instrument_id,
            "timeframe": tf,
            "price_basis": pb,
            "last_bar_ts": require_aware_utc(last_bar_ts, field="last_bar_ts") if last_bar_ts else None,
            "backfilled_from_ts": require_aware_utc(backfilled_from_ts, field="backfilled_from_ts")
            if backfilled_from_ts
            else None,
            "last_success_at": require_aware_utc(last_success_at, field="last_success_at")
            if last_success_at
            else None,
            "last_run_id": last_run_id,
        }
        stmt = pg_insert(IngestionState).values(**values)
        # The cursor is monotonic: last_bar_ts only advances (GREATEST), backfilled_from_ts
        # only recedes (LEAST). last_success_at / last_run_id take the newest non-null value.
        update_cols: dict = {"updated_at": func.now()}
        if values["last_bar_ts"] is not None:
            update_cols["last_bar_ts"] = func.greatest(
                func.coalesce(IngestionState.last_bar_ts, values["last_bar_ts"]), stmt.excluded.last_bar_ts
            )
        if values["backfilled_from_ts"] is not None:
            update_cols["backfilled_from_ts"] = func.least(
                func.coalesce(IngestionState.backfilled_from_ts, values["backfilled_from_ts"]),
                stmt.excluded.backfilled_from_ts,
            )
        if values["last_success_at"] is not None:
            update_cols["last_success_at"] = stmt.excluded.last_success_at
        if values["last_run_id"] is not None:
            update_cols["last_run_id"] = stmt.excluded.last_run_id

        stmt = (
            stmt.on_conflict_do_update(constraint="uq_ingestion_state_key", set_=update_cols)
            .returning(IngestionState)
        )
        m = (await self._session.execute(stmt)).scalar_one()
        return _state_row(m)
