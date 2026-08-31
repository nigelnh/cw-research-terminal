"""Read-only PostgreSQL access for the enrichment domains.

These functions NEVER contact an upstream source. If the table is empty they return an
empty result — the API layer turns that into a truthful empty state, not an error.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import String, and_, cast, desc, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.persistence.models import CompanyEvent, CompanyProfile, ExternalNews

_MAX_LIMIT = 100

# The "corporate action" subset of company events — price-sensitive distributions plus
# the meeting / listing events consumers expect from the pre-14B model.
_CA_CLASSES = ("DIVIDEND", "RIGHTS", "MEETING", "LISTING")


# --------------------------------------------------------------------------- news
async def list_news(
    session: AsyncSession,
    *,
    symbol: str | None = None,
    query: str | None = None,
    lang: str = "vi",
    limit: int = 30,
    before: datetime | None = None,
) -> list[ExternalNews]:
    limit = max(1, min(int(limit), _MAX_LIMIT))
    stmt = select(ExternalNews).where(ExternalNews.lang == lang)
    if symbol:
        stmt = stmt.where(ExternalNews.symbols.contains([symbol.upper()]))
    if query:
        like = f"%{query.strip()}%"
        stmt = stmt.where(ExternalNews.title.ilike(like))
    if before is not None:
        stmt = stmt.where(ExternalNews.published_at < before)
    stmt = stmt.order_by(desc(func.coalesce(ExternalNews.published_at, ExternalNews.observed_at))).limit(limit)
    return list((await session.execute(stmt)).scalars().all())


async def news_symbol_facets(session: AsyncSession, *, lang: str = "vi", limit: int = 40) -> list[str]:
    """Distinct symbols that appear in recent news, for a filter affordance."""
    stmt = (
        select(func.jsonb_array_elements_text(ExternalNews.symbols).label("sym"), func.count().label("n"))
        .where(ExternalNews.lang == lang)
        .group_by("sym")
        .order_by(desc("n"))
        .limit(limit)
    )
    return [r[0] for r in (await session.execute(stmt)).all()]


async def news_count_for_symbol(session: AsyncSession, symbol: str, *, lang: str = "vi") -> int:
    stmt = (
        select(func.count())
        .select_from(ExternalNews)
        .where(and_(ExternalNews.lang == lang, ExternalNews.symbols.contains([symbol.upper()])))
    )
    return int((await session.execute(stmt)).scalar() or 0)


# ------------------------------------------------------------------- company events
def _event_sort_col():
    return func.coalesce(
        CompanyEvent.ex_date,
        CompanyEvent.public_date,
        CompanyEvent.record_date,
        CompanyEvent.disclosure_date,
    )


async def list_company_events(
    session: AsyncSession,
    *,
    symbol: str,
    limit: int = 20,
    classes: list[str] | None = None,
    types: list[str] | None = None,
) -> list[CompanyEvent]:
    limit = max(1, min(int(limit), _MAX_LIMIT))
    stmt = select(CompanyEvent).where(CompanyEvent.symbol == symbol.upper())
    if classes:
        stmt = stmt.where(CompanyEvent.event_class.in_([c.upper() for c in classes]))
    if types:
        stmt = stmt.where(CompanyEvent.event_type.in_([t.upper() for t in types]))
    stmt = stmt.order_by(desc(_event_sort_col())).limit(limit)
    return list((await session.execute(stmt)).scalars().all())


async def list_corporate_actions(
    session: AsyncSession,
    *,
    symbol: str,
    limit: int = 20,
    action_types: list[str] | None = None,
) -> list[CompanyEvent]:
    """The price-adjustment + meeting subset — the pre-14B `corporate_actions` semantics."""
    limit = max(1, min(int(limit), _MAX_LIMIT))
    stmt = select(CompanyEvent).where(
        CompanyEvent.symbol == symbol.upper(),
        CompanyEvent.event_class.in_(_CA_CLASSES),
    )
    if action_types:
        stmt = stmt.where(CompanyEvent.event_type.in_(action_types))
    stmt = stmt.order_by(desc(_event_sort_col())).limit(limit)
    return list((await session.execute(stmt)).scalars().all())


async def get_company_profile(session: AsyncSession, symbol: str) -> CompanyProfile | None:
    stmt = select(CompanyProfile).where(CompanyProfile.symbol == symbol.upper())
    return (await session.execute(stmt)).scalar_one_or_none()


# --------------------------------------------------------------------- unified feed
@dataclass(slots=True)
class FeedRow:
    id: str
    symbol: str | None
    published_at: str | None
    title: str
    summary: str | None
    category: str | None
    content_type: str
    source: str
    source_url: str | None
    ev_class: str | None  # company_event rows only — for the English label
    ev_type: str | None
    _sort: datetime | date | None  # cursor key, not serialised


def _news_feed_select(lang: str):
    return select(
        (literal("news_") + cast(ExternalNews.id, String)).label("id"),
        ExternalNews.symbols.label("symbols"),
        cast(ExternalNews.published_at, String).label("published_at"),
        ExternalNews.title.label("title"),
        cast(ExternalNews.summary_html, String).label("summary"),
        ExternalNews.category.label("category"),
        ExternalNews.content_type.label("content_type"),
        ExternalNews.source.label("source"),
        ExternalNews.url.label("source_url"),
        literal(None).label("ev_class"),
        literal(None).label("ev_type"),
        cast(func.coalesce(ExternalNews.published_at, ExternalNews.observed_at), String).label("sort_ts"),
    ).where(ExternalNews.lang == lang)


def _event_feed_select():
    return select(
        (literal("event_") + cast(CompanyEvent.id, String)).label("id"),
        func.jsonb_build_array(CompanyEvent.symbol).label("symbols"),
        cast(_event_sort_col(), String).label("published_at"),
        func.concat(CompanyEvent.symbol, literal(" · "), func.coalesce(CompanyEvent.event_name, CompanyEvent.event_type)).label("title"),
        cast(CompanyEvent.note, String).label("summary"),
        CompanyEvent.event_class.label("category"),
        literal("company_event").label("content_type"),
        CompanyEvent.source.label("source"),
        CompanyEvent.url.label("source_url"),
        CompanyEvent.event_class.label("ev_class"),
        CompanyEvent.event_type.label("ev_type"),
        func.coalesce(
            cast(_event_sort_col(), String),
            cast(CompanyEvent.observed_at, String),
        ).label("sort_ts"),
    )


async def list_feed(
    session: AsyncSession,
    *,
    symbol: str | None = None,
    source: str | None = None,
    content_type: str | None = None,
    category: str | None = None,
    event_class: str | None = None,
    query: str | None = None,
    lang: str = "vi",
    limit: int = 30,
    before: str | None = None,
) -> tuple[list[FeedRow], bool]:
    """Unified, cursor-paginated research feed over news + company events.

    Returns (rows, has_more). The cursor is an ISO timestamp string on the row sort key;
    `before` pages backwards in time. Kept deliberately simple — a lexical string compare
    on the coalesced date works because all keys are ISO-ordered.
    """
    limit = max(1, min(int(limit), _MAX_LIMIT))
    want_news = content_type in (None, "exchange_disclosure")
    want_events = content_type in (None, "company_event")
    if source == "HOSE":
        want_events = False
    if source in ("SSI", "VNDIRECT"):
        want_news = False

    selects = []
    if want_news:
        ns = _news_feed_select(lang)
        if symbol:
            ns = ns.where(ExternalNews.symbols.contains([symbol.upper()]))
        if source:
            ns = ns.where(ExternalNews.source == source)
        if category:
            ns = ns.where(ExternalNews.category == category)
        if query:
            ns = ns.where(ExternalNews.title.ilike(f"%{query.strip()}%"))
        selects.append(ns)
    if want_events:
        es = _event_feed_select()
        if symbol:
            es = es.where(CompanyEvent.symbol == symbol.upper())
        if source:
            es = es.where(CompanyEvent.source == source)
        if event_class:
            es = es.where(CompanyEvent.event_class == event_class.upper())
        if query:
            es = es.where(
                or_(CompanyEvent.note.ilike(f"%{query.strip()}%"),
                    CompanyEvent.event_name.ilike(f"%{query.strip()}%"))
            )
        selects.append(es)

    if not selects:
        return [], False

    union = selects[0] if len(selects) == 1 else selects[0].union_all(*selects[1:])
    sub = union.subquery("feed")
    stmt = select(sub).order_by(desc(sub.c.sort_ts), desc(sub.c.id)).limit(limit + 1)
    if before:
        stmt = stmt.where(sub.c.sort_ts < before)
    elif not symbol:
        # Default market-wide view is "recent" — far-future scheduled listings (VNDirect /
        # SSI often carry effective dates years out) must not dominate the top of the feed.
        # A per-symbol view or an explicit cursor still reaches them.
        horizon = (date.today() + timedelta(days=14)).isoformat()
        stmt = stmt.where(sub.c.sort_ts <= horizon)

    raw = (await session.execute(stmt)).mappings().all()
    has_more = len(raw) > limit
    raw = raw[:limit]
    rows: list[FeedRow] = []
    for m in raw:
        syms = m["symbols"] or []
        rows.append(
            FeedRow(
                id=m["id"],
                symbol=(syms[0] if syms else None),
                published_at=(str(m["published_at"]) if m["published_at"] is not None else None),
                title=m["title"],
                summary=m["summary"],
                category=m["category"],
                content_type=m["content_type"],
                source=m["source"],
                source_url=m["source_url"],
                ev_class=m["ev_class"],
                ev_type=m["ev_type"],
                _sort=m["sort_ts"],
            )
        )
    return rows, has_more
