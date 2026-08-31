"""Idempotent upsert of normalized enrichment rows into PostgreSQL.

Every method is deterministic and retry-safe: conflicts on the natural key
(``source, source_id`` / ``symbol``) UPDATE in place. ``xmax = 0`` distinguishes an
INSERT from an ON CONFLICT UPDATE so a run can report inserted vs updated counts.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import func, literal_column, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.persistence.models import (
    CompanyEvent,
    CompanyProfile,
    ExternalNews,
)

logger = logging.getLogger("app.enrichment.service")

_INSERTED = literal_column("(xmax = 0)")


@dataclass(slots=True)
class UpsertResult:
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)

    def merge(self, other: "UpsertResult") -> None:
        self.inserted += other.inserted
        self.updated += other.updated
        self.skipped += other.skipped
        self.errors.extend(other.errors)


class EnrichmentService:
    def __init__(self, sessionmaker: async_sessionmaker) -> None:
        self._sm = sessionmaker

    # ---------------------------------------------------------------- news
    async def upsert_news(self, rows: list[dict]) -> UpsertResult:
        res = UpsertResult()
        clean = [r for r in rows if r.get("source_id") and r.get("title")]
        res.skipped += len(rows) - len(clean)
        if not clean:
            return res
        async with self._sm() as s:
            for r in clean:
                stmt = pg_insert(ExternalNews).values(
                    source=r["source"],
                    source_id=r["source_id"],
                    lang=r.get("lang", "vi"),
                    title=r["title"],
                    summary_html=r.get("summary_html"),
                    category=r.get("category"),
                    content_type=r.get("content_type", "exchange_disclosure"),
                    symbols=r.get("symbols") or [],
                    related_source_id=r.get("related_source_id"),
                    published_at=r.get("published_at"),
                    approved_at=r.get("approved_at"),
                    url=r.get("url"),
                    raw=r.get("raw") or {},
                )
                stmt = stmt.on_conflict_do_update(
                    constraint="uq_external_news_identity",
                    set_={
                        "title": stmt.excluded.title,
                        "summary_html": stmt.excluded.summary_html,
                        "category": stmt.excluded.category,
                        "content_type": stmt.excluded.content_type,
                        "symbols": stmt.excluded.symbols,
                        "published_at": stmt.excluded.published_at,
                        "approved_at": stmt.excluded.approved_at,
                        "url": stmt.excluded.url,
                        "raw": stmt.excluded.raw,
                        "updated_at": func.now(),
                    },
                ).returning(_INSERTED)
                inserted = (await s.execute(stmt)).scalar()
                if inserted:
                    res.inserted += 1
                else:
                    res.updated += 1
            await s.commit()
        return res

    # ------------------------------------------------------ company events
    async def upsert_company_events(self, rows: list[dict | None]) -> UpsertResult:
        """Upsert normalized company events (VNDirect or SSI) keyed on (source, source_id)."""
        res = UpsertResult()
        clean: list[dict] = [
            r for r in rows if r and r.get("source_id") and r.get("symbol") and r.get("event_type")
        ]
        res.skipped += len([r for r in rows if r]) - len(clean)
        if not clean:
            return res
        # de-dupe within the batch on (source, source_id); last wins
        by_key: dict[tuple, dict] = {}
        for r in clean:
            by_key[(r["source"], r["source_id"])] = r
        async with self._sm() as s:
            for r in by_key.values():
                stmt = pg_insert(CompanyEvent).values(
                    source=r["source"],
                    source_id=r["source_id"],
                    symbol=r["symbol"],
                    event_type=r["event_type"],
                    event_class=r.get("event_class", "OTHER"),
                    event_name=r.get("event_name"),
                    source_event_code=r.get("source_event_code"),
                    status=r.get("status", "UNKNOWN"),
                    ex_date=r.get("ex_date"),
                    record_date=r.get("record_date"),
                    payment_date=r.get("payment_date"),
                    disclosure_date=r.get("disclosure_date"),
                    public_date=r.get("public_date"),
                    cash_amount_vnd=r.get("cash_amount_vnd"),
                    ratio_pct=r.get("ratio_pct"),
                    ratio_text=r.get("ratio_text"),
                    value_text=r.get("value_text"),
                    dividend_year=r.get("dividend_year"),
                    note=r.get("note"),
                    url=r.get("url"),
                    raw=r.get("raw") or {},
                )
                stmt = stmt.on_conflict_do_update(
                    constraint="uq_company_events_identity",
                    set_={
                        "symbol": stmt.excluded.symbol,
                        "event_type": stmt.excluded.event_type,
                        "event_class": stmt.excluded.event_class,
                        "event_name": stmt.excluded.event_name,
                        "source_event_code": stmt.excluded.source_event_code,
                        "status": stmt.excluded.status,
                        "ex_date": stmt.excluded.ex_date,
                        "record_date": stmt.excluded.record_date,
                        "payment_date": stmt.excluded.payment_date,
                        "disclosure_date": stmt.excluded.disclosure_date,
                        "public_date": stmt.excluded.public_date,
                        "cash_amount_vnd": stmt.excluded.cash_amount_vnd,
                        "ratio_pct": stmt.excluded.ratio_pct,
                        "ratio_text": stmt.excluded.ratio_text,
                        "value_text": stmt.excluded.value_text,
                        "dividend_year": stmt.excluded.dividend_year,
                        "note": stmt.excluded.note,
                        "raw": stmt.excluded.raw,
                        "updated_at": func.now(),
                    },
                ).returning(_INSERTED)
                inserted = (await s.execute(stmt)).scalar()
                if inserted:
                    res.inserted += 1
                else:
                    res.updated += 1
            await s.commit()
        return res

    # backwards-compatible alias for the VNDirect ingestion path
    async def upsert_corporate_actions(self, rows: list[dict | None]) -> UpsertResult:
        return await self.upsert_company_events(rows)

    # ------------------------------------------------------ company profiles
    async def upsert_company_profile(self, row: dict | None) -> UpsertResult:
        res = UpsertResult()
        if not row or not row.get("symbol"):
            res.skipped += 1
            return res
        async with self._sm() as s:
            stmt = pg_insert(CompanyProfile).values(
                symbol=row["symbol"],
                exchange=row.get("exchange"),
                vn_name=row.get("vn_name"),
                en_name=row.get("en_name"),
                industry=row.get("industry"),
                found_date=row.get("found_date"),
                tax_code=row.get("tax_code"),
                website=row.get("website"),
                listed_shares=row.get("listed_shares"),
                outstanding_shares=row.get("outstanding_shares"),
                source=row.get("source", "VNDIRECT"),
                source_id=row.get("source_id"),
                raw=row.get("raw") or {},
            )
            stmt = stmt.on_conflict_do_update(
                constraint="uq_company_profiles_symbol",
                set_={
                    "exchange": stmt.excluded.exchange,
                    "vn_name": stmt.excluded.vn_name,
                    "en_name": stmt.excluded.en_name,
                    "industry": stmt.excluded.industry,
                    "found_date": stmt.excluded.found_date,
                    "tax_code": stmt.excluded.tax_code,
                    "website": stmt.excluded.website,
                    "listed_shares": stmt.excluded.listed_shares,
                    "outstanding_shares": stmt.excluded.outstanding_shares,
                    "raw": stmt.excluded.raw,
                    "observed_at": func.now(),
                    "updated_at": func.now(),
                },
            ).returning(_INSERTED)
            inserted = (await s.execute(stmt)).scalar()
            if inserted:
                res.inserted += 1
            else:
                res.updated += 1
            await s.commit()
        return res

    async def count(self, model) -> int:
        async with self._sm() as s:
            return int((await s.execute(select(func.count()).select_from(model))).scalar() or 0)
