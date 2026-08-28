"""Deterministic instrument seeding: InstrumentRegistry -> Step-5 ``instruments`` table.

Idempotent and rerunnable. Row identity (``id``) is stable across reruns because
``InstrumentRepository.upsert`` keys on ``symbol``.

What is mapped:
  * every covered warrant in the registry  -> instrument_type CW
  * every distinct underlying it references -> instrument_type STOCK (derived)
  * a small fixed set of HOSE/HNX indices   -> instrument_type INDEX (opt-in)

Only compact, useful provenance goes into ``attributes`` (issuer, lifecycle status, data
quality) - never the whole registry record.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime

from app.instruments.instrument_registry import instrument_registry
from app.instruments.instrument_schemas import (
    CoveredWarrantSpecification,
    DataQualityStatus,
    InstrumentLifecycleStatus,
)
from app.persistence.database import session_scope
from app.persistence.repositories.instrument_repository import InstrumentRepository, InstrumentUpsert

logger = logging.getLogger(__name__)

# Well-known Vietnamese market indices (not present in the CW registry). Kept minimal and
# explicit rather than "invented".
KNOWN_INDICES: tuple[tuple[str, str], ...] = (
    ("VNINDEX", "HOSE"),
    ("VN30", "HOSE"),
    ("HNXINDEX", "HNX"),
    ("HNX30", "HNX"),
    ("UPCOM", "UPCOM"),
)


@dataclass(frozen=True, slots=True)
class SeedReport:
    stocks_seeded: int
    indices_seeded: int
    warrants_seeded: int
    underlyings_resolved: int
    warrants_unresolved_underlying: list[str]
    active_count: int
    inactive_count: int

    @property
    def total(self) -> int:
        return self.stocks_seeded + self.indices_seeded + self.warrants_seeded


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value.strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _warrant_upsert(spec: CoveredWarrantSpecification) -> InstrumentUpsert:
    is_active = spec.status == InstrumentLifecycleStatus.ACTIVE
    # last trading date: prefer explicit last_trading_date, else maturity_date
    last_td = _parse_iso_date(spec.last_trading_date) or _parse_iso_date(spec.maturity_date)
    attributes: dict = {
        "issuer": spec.issuer or None,
        "lifecycle_status": spec.status.value,
        "data_quality": spec.data_quality.value,
        "metadata_verification": spec.metadata_verification.value,
    }
    if spec.data_quality == DataQualityStatus.PARTIAL:
        attributes["partial_metadata"] = True
    # incomplete CW metadata must NOT block raw bar ingestion: we still seed the row.
    return InstrumentUpsert(
        symbol=spec.symbol,
        instrument_type="CW",
        exchange="HOSE",
        currency="VND",
        underlying_symbol=(spec.underlying_symbol or None),
        is_active=is_active,
        last_trade_date=last_td,
        metadata={k: v for k, v in attributes.items() if v is not None},
    )


async def seed_instruments(*, include_indices: bool = True, registry_current_date: str | None = None) -> SeedReport:
    """Seed the ``instruments`` table from the canonical registry. Idempotent."""
    await instrument_registry.initialize(current_date=registry_current_date)
    # every warrant, regardless of lifecycle - EXPIRED/UNKNOWN CWs still get a row
    warrants: list[CoveredWarrantSpecification] = await instrument_registry.search(active_only=False)
    warrants.sort(key=lambda s: s.symbol)

    underlyings = sorted({(s.underlying_symbol or "").strip().upper() for s in warrants} - {""})

    stocks_seeded = 0
    indices_seeded = 0
    warrants_seeded = 0
    active_count = 0
    inactive_count = 0

    async with session_scope() as session:
        repo = InstrumentRepository(session)

        # Pass 1: non-CW first so CW underlying FKs resolve immediately.
        for sym in underlyings:
            await repo.upsert(
                InstrumentUpsert(
                    symbol=sym, instrument_type="STOCK", exchange="HOSE", currency="VND",
                    is_active=True, metadata={"derived_from": "cw_underlying"},
                )
            )
            stocks_seeded += 1

        if include_indices:
            for sym, exch in KNOWN_INDICES:
                await repo.upsert(
                    InstrumentUpsert(
                        symbol=sym, instrument_type="INDEX", exchange=exch, currency="VND",
                        is_active=True, metadata={"seed": "known_index"},
                    )
                )
                indices_seeded += 1

        # Pass 2: warrants.
        for spec in warrants:
            row = await repo.upsert(_warrant_upsert(spec))
            warrants_seeded += 1
            if row.is_active:
                active_count += 1
            else:
                inactive_count += 1

    # Verify underlying resolution in a fresh read.
    unresolved: list[str] = []
    resolved = 0
    async with session_scope() as session:
        repo = InstrumentRepository(session)
        for spec in warrants:
            und = (spec.underlying_symbol or "").strip().upper()
            if not und:
                continue
            r = await repo.get_by_symbol(spec.symbol)
            if r is not None and r.underlying_instrument_id is not None:
                resolved += 1
            else:
                unresolved.append(spec.symbol)

    report = SeedReport(
        stocks_seeded=stocks_seeded,
        indices_seeded=indices_seeded,
        warrants_seeded=warrants_seeded,
        underlyings_resolved=resolved,
        warrants_unresolved_underlying=sorted(unresolved),
        active_count=active_count,
        inactive_count=inactive_count,
    )
    logger.info(
        "seed complete: %d stocks, %d indices, %d warrants (%d active / %d inactive); "
        "%d warrant->underlying links resolved, %d unresolved",
        report.stocks_seeded, report.indices_seeded, report.warrants_seeded,
        report.active_count, report.inactive_count, report.underlyings_resolved,
        len(report.warrants_unresolved_underlying),
    )
    return report
