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
from app.enrichment.english import (
    category_en,
    event_class_label_en,
    event_label_en,
    headline_en,
)
from app.persistence import database as persistence_db

logger = logging.getLogger("cw-research-backend.research")

research_router = APIRouter(prefix="/api/research", tags=["Research Enrichment"])


class NewsItem(BaseModel):
    id: int
    # English-first (docs/design/LANGUAGE_POLICY.md). `*_en` are the default display
    # fields; the raw Vietnamese `title` / `category` / `summary` are kept for provenance.
    title_en: str
    title_en_exact: bool          # False => a category/verb classification, not a rendered translation
    category_en: str
    title: str                    # original HOSE wording, verbatim
    summary: str | None           # original Vietnamese summary, verbatim
    category: str | None          # original HOSE catName
    source_language: str
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
    event_label: str            # English display label (from event_class / event_type)
    action_type: str            # kept for backwards compatibility (== event_type)
    event_type: str
    event_class: str
    event_name: str | None = None   # original Vietnamese, provenance only
    source_language: str = "vi"
    status: str
    ex_date: str | None
    record_date: str | None
    payment_date: str | None
    disclosure_date: str | None
    public_date: str | None = None
    cash_amount_vnd: float | None
    ratio_pct: float | None
    ratio_text: str | None
    value_text: str | None = None
    dividend_year: int | None
    note: str | None
    source: str


class FeedItem(BaseModel):
    id: str
    symbol: str | None
    published_at: str | None
    title_en: str
    title_en_exact: bool
    category_en: str
    title: str                  # original Vietnamese, verbatim
    summary: str | None         # original Vietnamese summary / event note
    category: str | None        # original HOSE catName / event_class
    source_language: str
    content_type: str
    source: str
    source_url: str | None


class FeedResponse(BaseModel):
    items: list[FeedItem]
    count: int
    has_more: bool
    next_before: str | None


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
    items = []
    for r in rows:
        syms = r.symbols or []
        t_en, exact = headline_en(r.title, category=r.category, symbol=(syms[0] if syms else None))
        items.append(
            NewsItem(
                id=r.id,
                title_en=t_en,
                title_en_exact=exact,
                category_en=category_en(r.category),
                title=r.title,
                summary=_strip_html(r.summary_html),
                category=r.category,
                source_language=r.lang or "vi",
                symbols=syms,
                published_at=_iso(r.published_at),
                url=r.url,
                source=r.source,
            )
        )
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


def _event_item(r) -> CorporateActionItem:
    return CorporateActionItem(
        id=r.id,
        symbol=r.symbol,
        event_label=event_label_en(r.event_class, r.event_type),
        action_type=r.event_type,
        event_type=r.event_type,
        event_class=r.event_class,
        event_name=r.event_name,
        status=r.status,
        ex_date=_iso(r.ex_date),
        record_date=_iso(r.record_date),
        payment_date=_iso(r.payment_date),
        disclosure_date=_iso(r.disclosure_date),
        public_date=_iso(r.public_date),
        cash_amount_vnd=float(r.cash_amount_vnd) if r.cash_amount_vnd is not None else None,
        ratio_pct=float(r.ratio_pct) if r.ratio_pct is not None else None,
        ratio_text=r.ratio_text,
        value_text=r.value_text,
        dividend_year=r.dividend_year,
        note=r.note,
        source=r.source,
    )


@research_router.get("/corporate-actions/{symbol}")
async def get_corporate_actions(
    symbol: str,
    limit: int = Query(default=20, ge=1, le=100),
):
    """Price-adjustment + meeting + listing events (the pre-14B corporate-actions view)."""
    if not persistence_db.is_configured():
        return {"symbol": symbol.upper(), "items": [], "count": 0}
    maker = persistence_db.get_sessionmaker()
    async with maker() as s:
        rows = await repo.list_corporate_actions(s, symbol=symbol, limit=limit)
    items = [_event_item(r) for r in rows]
    return {"symbol": symbol.upper(), "items": items, "count": len(items)}


@research_router.get("/events/{symbol}")
async def get_company_events(
    symbol: str,
    limit: int = Query(default=30, ge=1, le=100),
    event_class: str | None = Query(default=None, description="DIVIDEND|RIGHTS|MEETING|LISTING|FINANCIAL|OWNERSHIP|OTHER"),
):
    """The full company-event stream for a symbol (financials + insider + actions)."""
    if not persistence_db.is_configured():
        return {"symbol": symbol.upper(), "items": [], "count": 0}
    classes = [c.strip().upper() for c in event_class.split(",")] if event_class else None
    maker = persistence_db.get_sessionmaker()
    async with maker() as s:
        rows = await repo.list_company_events(s, symbol=symbol, limit=limit, classes=classes)
    items = [_event_item(r) for r in rows]
    return {"symbol": symbol.upper(), "items": items, "count": len(items)}


@research_router.get("/feed", response_model=FeedResponse)
async def get_feed(
    symbol: str | None = Query(default=None, max_length=32),
    source: str | None = Query(default=None, description="HOSE|SSI|VNDIRECT"),
    content_type: str | None = Query(default=None, description="exchange_disclosure|company_event"),
    category: str | None = Query(default=None, max_length=200),
    event_class: str | None = Query(default=None, max_length=20),
    q: str | None = Query(default=None, max_length=120),
    lang: str = Query(default="vi", pattern="^(vi|en)$"),
    limit: int = Query(default=30, ge=1, le=100),
    before: str | None = Query(default=None, description="cursor: sort_ts of the last row seen"),
):
    if not persistence_db.is_configured():
        return FeedResponse(items=[], count=0, has_more=False, next_before=None)
    maker = persistence_db.get_sessionmaker()
    async with maker() as s:
        rows, has_more = await repo.list_feed(
            s, symbol=symbol, source=source, content_type=content_type, category=category,
            event_class=event_class, query=q, lang=lang, limit=limit, before=before,
        )
    items = []
    for r in rows:
        if r.content_type == "company_event":
            label = event_label_en(r.ev_class, r.ev_type)
            t_en = f"{r.symbol} · {label}" if r.symbol else label
            exact = True
            cat_en = event_class_label_en(r.ev_class)
        else:
            t_en, exact = headline_en(r.title, category=r.category, symbol=r.symbol)
            cat_en = category_en(r.category)
        items.append(
            FeedItem(
                id=r.id, symbol=r.symbol, published_at=r.published_at,
                title_en=t_en, title_en_exact=exact, category_en=cat_en,
                title=r.title, summary=_strip_html(r.summary), category=r.category,
                source_language="vi",  # HOSE disclosures + SSI/VNDirect event text are Vietnamese at source
                content_type=r.content_type, source=r.source, source_url=r.source_url,
            )
        )
    next_before = str(rows[-1]._sort) if (has_more and rows) else None
    return FeedResponse(items=items, count=len(items), has_more=has_more, next_before=next_before)


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
