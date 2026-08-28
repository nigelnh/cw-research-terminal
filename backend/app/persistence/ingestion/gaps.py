"""Conservative gap detection and explicit, non-destructive repair.

The repo has no authoritative HOSE holiday calendar, so this classifies rather than
asserts:

    KNOWN_GAP          weekend / fixed public holiday -> never reported (expected)
    SUSPICIOUS         an isolated missing weekday session between present sessions
    UNKNOWN_CALENDAR   a multi-day missing-weekday run, or a day inside the approximate
                       Lunar New Year window -> probably a holiday we can't confirm

Repair re-fetches only SUSPICIOUS ranges (opt-in: also UNKNOWN_CALENDAR) through the
normal provider-safe chunked path and upserts. It never deletes surrounding data.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.persistence.ingestion.service import IngestionService
from app.persistence.ingestion.trading_calendar import (
    in_tet_window,
    is_expected_trading_day,
    last_completed_session_date,
)
from app.persistence.market_time import normalize_price_basis, normalize_timeframe
from app.persistence.repositories.instrument_repository import InstrumentRepository
from app.persistence.repositories.market_bar_repository import MarketBarRepository

logger = logging.getLogger(__name__)

_CLUSTER_THRESHOLD = 3  # >= this many consecutive missing weekdays -> UNKNOWN_CALENDAR


@dataclass(frozen=True, slots=True)
class GapSegment:
    start: date
    end: date
    classification: str        # SUSPICIOUS | UNKNOWN_CALENDAR
    missing_days: int

    def as_dict(self) -> dict:
        return {
            "start": self.start.isoformat(), "end": self.end.isoformat(),
            "classification": self.classification, "missing_days": self.missing_days,
        }


@dataclass
class GapReport:
    symbol: str
    timeframe: str
    price_basis: str
    scan_start: date
    scan_end: date
    seeded: bool
    bar_count: int
    expected_sessions: int
    present_sessions: int
    segments: list[GapSegment] = field(default_factory=list)

    @property
    def suspicious(self) -> list[GapSegment]:
        return [s for s in self.segments if s.classification == "SUSPICIOUS"]

    @property
    def unknown_calendar(self) -> list[GapSegment]:
        return [s for s in self.segments if s.classification == "UNKNOWN_CALENDAR"]

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol, "timeframe": self.timeframe, "price_basis": self.price_basis,
            "scan_start": self.scan_start.isoformat(), "scan_end": self.scan_end.isoformat(),
            "seeded": self.seeded, "bar_count": self.bar_count,
            "expected_sessions": self.expected_sessions, "present_sessions": self.present_sessions,
            "segments": [s.as_dict() for s in self.segments],
        }


async def detect_gaps(
    service: IngestionService,
    *,
    symbol: str,
    timeframe: str,
    adjusted: bool,
    from_date: date,
    to_date: date,
) -> GapReport:
    sym = symbol.strip().upper()
    tf = normalize_timeframe(timeframe)
    pb = normalize_price_basis(adjusted=adjusted)

    async with service._sm() as session:  # noqa: SLF001 - service owns the sessionmaker
        inst = await InstrumentRepository(session).get_by_symbol(sym)
        if inst is None:
            return GapReport(sym, tf, pb, from_date, to_date, seeded=False, bar_count=0,
                             expected_sessions=0, present_sessions=0)
        bars = await MarketBarRepository(session).get_bars(
            instrument_id=inst.id, timeframe=tf, price_basis=pb, ascending=True,
        )

    # bound the scan by listing / maturity where known, and never past the last completed session
    lo = from_date
    hi = min(to_date, last_completed_session_date())
    if inst.first_trade_date and inst.first_trade_date > lo:
        lo = inst.first_trade_date
    if inst.last_trade_date and inst.last_trade_date < hi:
        hi = inst.last_trade_date

    present: set[date] = {b.session_date for b in bars if lo <= b.session_date <= hi}
    expected = [d for d in _iter(lo, hi) if is_expected_trading_day(d)]
    missing = [d for d in expected if d not in present]

    segments = _classify_missing(missing)
    return GapReport(
        symbol=sym, timeframe=tf, price_basis=pb, scan_start=lo, scan_end=hi, seeded=True,
        bar_count=len(bars), expected_sessions=len(expected), present_sessions=len(expected) - len(missing),
        segments=segments,
    )


def _iter(lo: date, hi: date):
    d = lo
    while d <= hi:
        yield d
        d += timedelta(days=1)


def _classify_missing(missing: list[date]) -> list[GapSegment]:
    """Group consecutive *expected trading days* that are missing into runs, then classify.

    Two missing expected days separated only by a weekend still count as one run (the
    weekend days are simply not 'expected')."""
    if not missing:
        return []
    runs: list[list[date]] = []
    cur = [missing[0]]
    for prev, d in zip(missing, missing[1:], strict=False):
        # same run if no *expected trading day* sits between prev and d
        gap_has_expected = any(
            is_expected_trading_day(x) for x in _iter(prev + timedelta(days=1), d - timedelta(days=1))
        )
        if gap_has_expected:
            runs.append(cur)
            cur = [d]
        else:
            cur.append(d)
    runs.append(cur)

    segments: list[GapSegment] = []
    for run in runs:
        n = len(run)
        tet = any(in_tet_window(d) for d in run)
        classification = "UNKNOWN_CALENDAR" if (tet or n >= _CLUSTER_THRESHOLD) else "SUSPICIOUS"
        segments.append(GapSegment(start=run[0], end=run[-1], classification=classification, missing_days=n))
    return segments


@dataclass
class RepairResult:
    symbol: str
    timeframe: str
    price_basis: str
    before: GapReport
    after: GapReport | None
    repaired_segments: list[GapSegment]
    dry_run: bool
    backfill_status: str | None = None

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol, "timeframe": self.timeframe, "price_basis": self.price_basis,
            "dry_run": self.dry_run, "backfill_status": self.backfill_status,
            "repaired_segments": [s.as_dict() for s in self.repaired_segments],
            "suspicious_before": len(self.before.suspicious),
            "suspicious_after": (len(self.after.suspicious) if self.after else None),
            "unknown_calendar_before": len(self.before.unknown_calendar),
        }


async def repair_gaps(
    service: IngestionService,
    *,
    symbol: str,
    timeframe: str,
    adjusted: bool,
    from_date: date,
    to_date: date,
    include_unknown: bool = False,
    dry_run: bool = False,
) -> RepairResult:
    before = await detect_gaps(
        service, symbol=symbol, timeframe=timeframe, adjusted=adjusted,
        from_date=from_date, to_date=to_date,
    )
    targets = list(before.suspicious)
    if include_unknown:
        targets += before.unknown_calendar

    if not targets or dry_run:
        return RepairResult(
            symbol=before.symbol, timeframe=before.timeframe, price_basis=before.price_basis,
            before=before, after=None, repaired_segments=targets, dry_run=dry_run,
            backfill_status="DRY_RUN" if dry_run else ("NOTHING_TO_REPAIR" if not targets else None),
        )

    # Re-fetch each suspicious range (small pad so a boundary session is included), force
    # so idempotent upsert actually re-queries; never deletes.
    pad = timedelta(days=2)
    statuses: list[str] = []
    for seg in targets:
        res = await service.backfill(
            [symbol], timeframe=timeframe, adjusted=adjusted,
            from_date=seg.start - pad, to_date=seg.end + pad,
            dry_run=False, force=True,
        )
        statuses.append(res.status)

    after = await detect_gaps(
        service, symbol=symbol, timeframe=timeframe, adjusted=adjusted,
        from_date=from_date, to_date=to_date,
    )
    return RepairResult(
        symbol=before.symbol, timeframe=before.timeframe, price_basis=before.price_basis,
        before=before, after=after, repaired_segments=targets, dry_run=False,
        backfill_status=("PARTIAL" if any(s != "SUCCEEDED" for s in statuses) else "SUCCEEDED"),
    )
