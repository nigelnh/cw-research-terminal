"""Public read APIs for enrichment domains. PostgreSQL-only — never contacts a source.

    GET /api/research/news
    GET /api/research/news/facets
    GET /api/research/corporate-actions/{symbol}
    GET /api/research/company/{symbol}

When the persistence layer is not configured every endpoint returns an empty, well-formed
payload (200) rather than a 503 — a fresh deploy with no ingestion yet is a valid state.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.enrichment import repository as repo
from app.persistence import database as persistence_db

logger = logging.getLogger("cw-research-backend.research")

research_router = APIRouter(prefix="/api/research", tags=["Research Enrichment"])


class NewsItem(BaseModel):
    id: int
    title: str
    summary: str | None
    category: str | None
    symbols: list[str]
    published_at: str | None
    url: str | None
    source: str


class NewsResponse(BaseModel):
    items: list[NewsItem]
    count: int
    has_more: bool
    next_before: str | None


class CorporateActionItem(BaseModel):
    id: int
    symbol: str
    action_type: str
    status: str
    ex_date: str | None
    record_date: str | None
    payment_date: str | None
    disclosure_date: str | None
    cash_amount_vnd: float | None
    ratio_pct: float | None
    ratio_text: str | None
    dividend_year: int | None
    note: str | None
    source: str


class CompanyProfileResponse(BaseModel):
    symbol: str
    exchange: str | None
    vn_name: str | None
    en_name: str | None
    industry: str | None
    found_date: str | None
    website: str | None
    listed_shares: int | None
    outstanding_shares: int | None
    news_count: int
    source: str | None


def _iso(d: Any) -> str | None:
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.astimezone(timezone.utc).isoformat()
    return d.isoformat()


def _strip_html(s: str | None) -> str | None:
    from app.enrichment.normalize import strip_html

    return strip_html(s)


@research_router.get("/news", response_model=NewsResponse)
async def get_news_feed(
    symbol: str | None = Query(default=None, max_length=32),
    q: str | None = Query(default=None, max_length=120),
    lang: str = Query(default="vi", pattern="^(vi|en)$"),
    limit: int = Query(default=30, ge=1, le=100),
    before: str | None = Query(default=None, description="ISO timestamp for cursor pagination"),
):
    if not persistence_db.is_configured():
        return NewsResponse(items=[], count=0, has_more=False, next_before=None)

    before_dt: datetime | None = None
    if before:
        try:
            before_dt = datetime.fromisoformat(before.replace("Z", "+00:00"))
        except ValueError:
            before_dt = None

    maker = persistence_db.get_sessionmaker()
    async with maker() as s:
        rows = await repo.list_news(
            s, symbol=symbol, query=q, lang=lang, limit=limit + 1, before=before_dt
        )
    has_more = len(rows) > limit
    rows = rows[:limit]
    items = [
        NewsItem(
            id=r.id,
            title=r.title,
            summary=_strip_html(r.summary_html),
            category=r.category,
            symbols=r.symbols or [],
            published_at=_iso(r.published_at),
            url=r.url,
            source=r.source,
        )
        for r in rows
    ]
    next_before = _iso(rows[-1].published_at) if (has_more and rows and rows[-1].published_at) else None
    return NewsResponse(items=items, count=len(items), has_more=has_more, next_before=next_before)


@research_router.get("/news/facets")
async def get_news_facets(lang: str = Query(default="vi", pattern="^(vi|en)$")):
    if not persistence_db.is_configured():
        return {"symbols": []}
    maker = persistence_db.get_sessionmaker()
    async with maker() as s:
        syms = await repo.news_symbol_facets(s, lang=lang)
    return {"symbols": syms}


@research_router.get("/corporate-actions/{symbol}")
async def get_corporate_actions(
    symbol: str,
    limit: int = Query(default=20, ge=1, le=100),
):
    if not persistence_db.is_configured():
        return {"symbol": symbol.upper(), "items": [], "count": 0}
    maker = persistence_db.get_sessionmaker()
    async with maker() as s:
        rows = await repo.list_corporate_actions(s, symbol=symbol, limit=limit)
    items = [
        CorporateActionItem(
            id=r.id,
            symbol=r.symbol,
            action_type=r.action_type,
            status=r.status,
            ex_date=_iso(r.ex_date),
            record_date=_iso(r.record_date),
            payment_date=_iso(r.payment_date),
            disclosure_date=_iso(r.disclosure_date),
            cash_amount_vnd=float(r.cash_amount_vnd) if r.cash_amount_vnd is not None else None,
            ratio_pct=float(r.ratio_pct) if r.ratio_pct is not None else None,
            ratio_text=r.ratio_text,
            dividend_year=r.dividend_year,
            note=r.note,
            source=r.source,
        )
        for r in rows
    ]
    return {"symbol": symbol.upper(), "items": items, "count": len(items)}


@research_router.get("/company/{symbol}", response_model=CompanyProfileResponse)
async def get_company(symbol: str):
    sym = symbol.upper()
    if not persistence_db.is_configured():
        return CompanyProfileResponse(
            symbol=sym, exchange=None, vn_name=None, en_name=None, industry=None,
            found_date=None, website=None, listed_shares=None, outstanding_shares=None,
            news_count=0, source=None,
        )
    maker = persistence_db.get_sessionmaker()
    async with maker() as s:
        p = await repo.get_company_profile(s, sym)
        ncount = await repo.news_count_for_symbol(s, sym)
    if p is None:
        return CompanyProfileResponse(
            symbol=sym, exchange=None, vn_name=None, en_name=None, industry=None,
            found_date=None, website=None, listed_shares=None, outstanding_shares=None,
            news_count=ncount, source=None,
        )
    return CompanyProfileResponse(
        symbol=p.symbol,
        exchange=p.exchange,
        vn_name=p.vn_name,
        en_name=p.en_name,
        industry=p.industry,
        found_date=_iso(p.found_date),
        website=p.website,
        listed_shares=p.listed_shares,
        outstanding_shares=p.outstanding_shares,
        news_count=ncount,
        source=p.source,
    )
