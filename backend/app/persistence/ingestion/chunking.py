"""Provider-safe chronological request-window generation.

The FiinQuant gateway rejects historical requests that reach too far back
(empirically: a narrow window ~18 months old returns HTTP 403; a ~355-day span with a
small lookback returns 200). Two independent limits therefore matter:

* **max lookback from today** - how old the oldest requested date may be
  (``INGEST_MAX_LOOKBACK_DAYS``, default 360; this account's entitlement is ~1 year).
* **max request span** - how wide a single request window may be
  (``INGEST_MAX_CHUNK_SPAN_DAYS``, default 350; safely inside the observed ~355).

``plan_backfill_windows`` clamps an explicit request against the lookback limit
(reporting the clamp - never silently) and splits the accessible portion into
contiguous, non-overlapping, span-bounded chunks.

Chunk boundary contract
-----------------------
FiinQuant ``from_date``/``to_date`` are **inclusive on both ends**. Chunk ``N+1`` starts
the calendar day *after* chunk ``N`` ends, so the union of chunks equals the requested
(post-clamp) range exactly: no missing calendar date, no overlap. Database uniqueness
would absorb accidental duplicates, but chunk generation does not rely on that.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from app.core.config import settings


@dataclass(frozen=True, slots=True)
class Chunk:
    """One inclusive ``[start, end]`` calendar-date request window (chronological index ``seq``)."""

    seq: int
    start: date
    end: date

    @property
    def span_days(self) -> int:
        return (self.end - self.start).days

    def as_iso(self) -> tuple[str, str]:
        return self.start.isoformat(), self.end.isoformat()


@dataclass(frozen=True, slots=True)
class BackfillPlan:
    requested_start: date
    requested_end: date
    effective_start: date          # after lookback clamp
    effective_end: date
    chunks: tuple[Chunk, ...]
    lookback_clamped: bool         # True => requested_start was older than the entitlement horizon
    clamp_note: str | None

    @property
    def is_empty(self) -> bool:
        return len(self.chunks) == 0

    @property
    def total_span_days(self) -> int:
        return (self.effective_end - self.effective_start).days if not self.is_empty else 0


def generate_chunks(
    start: date,
    end: date,
    *,
    max_span_days: int,
    _seq_offset: int = 0,
) -> list[Chunk]:
    """Split the inclusive ``[start, end]`` range into contiguous ``<= max_span_days`` chunks.

    Examples (max_span_days=350):
      [2026-08-01, 2026-08-10]                 -> 1 chunk  [08-01, 08-10]  span 9
      [2025-08-28, 2026-08-28] (365d)          -> [2025-08-28, 2026-08-13] span350
                                                  [2026-08-14, 2026-08-28] span14
      [d, d]                                   -> 1 chunk  [d, d]          span 0
      [d, d + 350]                             -> 1 chunk  span 350
      [d, d + 351]                             -> [d, d+350] span350 ; [d+351, d+351] span0
    """
    if max_span_days < 1:
        raise ValueError(f"max_span_days must be >= 1, got {max_span_days}")
    if start > end:
        raise ValueError(f"start {start} is after end {end}")

    chunks: list[Chunk] = []
    cursor = start
    seq = _seq_offset
    step = timedelta(days=max_span_days)
    one_day = timedelta(days=1)
    while cursor <= end:
        chunk_end = min(cursor + step, end)
        chunks.append(Chunk(seq=seq, start=cursor, end=chunk_end))
        cursor = chunk_end + one_day
        seq += 1
    return chunks


def plan_backfill_windows(
    requested_start: date,
    requested_end: date,
    *,
    today: date,
    max_span_days: int | None = None,
    max_lookback_days: int | None = None,
) -> BackfillPlan:
    """Clamp an explicit backfill request to the accessible horizon and chunk it.

    ``requested_start`` older than ``today - max_lookback_days`` is **clamped** (with
    ``lookback_clamped=True`` and a human-readable ``clamp_note``) - the ingestion layer
    never issues a provider request it knows will 403, and never silently pretends the
    full range was covered.
    """
    span_limit = int(max_span_days if max_span_days is not None else settings.INGEST_MAX_CHUNK_SPAN_DAYS)
    lookback_limit = int(
        max_lookback_days if max_lookback_days is not None else settings.INGEST_MAX_LOOKBACK_DAYS
    )
    if requested_start > requested_end:
        raise ValueError(f"requested_start {requested_start} is after requested_end {requested_end}")

    horizon = today - timedelta(days=lookback_limit)
    effective_start = requested_start
    clamped = False
    note: str | None = None
    if requested_start < horizon:
        clamped = True
        effective_start = horizon
        note = (
            f"requested start {requested_start.isoformat()} is older than the accessible "
            f"provider horizon ({lookback_limit}-day lookback -> {horizon.isoformat()}); "
            f"fetch clamped to {horizon.isoformat()}. Older history requires a different source."
        )

    # end is never in the future beyond today for the fetch; caller decides the completed-bar cutoff
    effective_end = min(requested_end, today)

    if effective_start > effective_end:
        return BackfillPlan(
            requested_start=requested_start,
            requested_end=requested_end,
            effective_start=effective_start,
            effective_end=effective_end,
            chunks=(),
            lookback_clamped=clamped,
            clamp_note=note or "requested range is entirely outside the accessible horizon",
        )

    chunks = tuple(generate_chunks(effective_start, effective_end, max_span_days=span_limit))
    return BackfillPlan(
        requested_start=requested_start,
        requested_end=requested_end,
        effective_start=effective_start,
        effective_end=effective_end,
        chunks=chunks,
        lookback_clamped=clamped,
        clamp_note=note,
    )
