"""Read-only PostgreSQL access for the enrichment domains.

These functions NEVER contact an upstream source. If the table is empty they return an
empty result — the API layer turns that into a truthful empty state, not an error.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import base64
import json
import re
from zoneinfo import ZoneInfo

from sqlalchemy import (
    String, Date, DateTime, and_, case, cast, desc, func, literal, literal_column, or_, select, text,
)
from app.enrichment.english import headline_search_label, event_search_label
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import array

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
    if before is not None:
        stmt = stmt.where(ExternalNews.published_at < before)

    text_query = (query or "").strip()
    if text_query:
        # Relevance, not substring. `websearch_to_tsquery` accepts what people actually
        # type (bare words, "quoted phrases", -exclusions) and never raises on syntax, so a
        # user question can be passed through unsanitised. `simple` + f_unaccent match the
        # generated column exactly - any divergence would silently return nothing.
        tsq = func.websearch_to_tsquery("simple", func.f_unaccent(text_query))
        stmt = stmt.where(literal_column("search_tsv").op("@@")(tsq))
        # Blend relevance with recency: a well-matched article from two years ago should
        # not outrank a good match from yesterday on a market desk. The denominator halves
        # the score at roughly 180 days.
        age_days = func.extract(
            "epoch",
            func.now() - func.coalesce(ExternalNews.published_at, ExternalNews.observed_at),
        ) / 86400.0
        score = func.ts_rank(literal_column("search_tsv"), tsq) / (1.0 + age_days / 180.0)
        stmt = stmt.order_by(desc(score), desc(func.coalesce(ExternalNews.published_at, ExternalNews.observed_at)))
    else:
        stmt = stmt.order_by(desc(func.coalesce(ExternalNews.published_at, ExternalNews.observed_at)))

    return list((await session.execute(stmt.limit(limit))).scalars().all())


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


async def get_company_profiles(
    session: AsyncSession, symbols: list[str]
) -> dict[str, CompanyProfile]:
    """Batch profile lookup used by market-data fallbacks; never contacts upstream."""
    clean = sorted({symbol.strip().upper() for symbol in symbols if symbol and symbol.strip()})
    if not clean:
        return {}
    stmt = select(CompanyProfile).where(CompanyProfile.symbol.in_(clean))
    return {row.symbol: row for row in (await session.execute(stmt)).scalars().all()}


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
    ev_class: str | None
    ev_type: str | None
    _sort: datetime | date | None
    display_date: str | None = None
    date_kind: str = "published"


def encode_feed_cursor(row: FeedRow) -> str:
    stamp = row._sort.isoformat() if isinstance(row._sort, (datetime, date)) else str(row._sort)
    return base64.urlsafe_b64encode(json.dumps([stamp, row.id]).encode()).decode().rstrip("=")


def decode_feed_cursor(value: str) -> tuple[datetime, str]:
    try:
        if len(value) > 512:
            raise ValueError()
        stamp, ident = json.loads(base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True))
        if not isinstance(ident, str) or not re.fullmatch(r"(?:news|event)_\d+", ident):
            raise ValueError()
        dt = datetime.fromisoformat(stamp)
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt, ident
    except (ValueError, TypeError, UnicodeError) as exc:
        raise ValueError("Invalid feed cursor") from exc


def _news_feed_select(lang: str):
    stamp = func.coalesce(ExternalNews.published_at, ExternalNews.observed_at)
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
        literal(None).label("ev_class"), literal(None).label("ev_type"),
        stamp.label("sort_ts"),
        case((ExternalNews.published_at.is_not(None), "published"), else_="observed").label("date_kind"),
    ).where(ExternalNews.lang == lang)


def _event_feed_select():
    # Event dates are Vietnam calendar dates, not publication timestamps.
    event_stamp = func.timezone("Asia/Ho_Chi_Minh", cast(_event_sort_col(), DateTime))
    stamp = func.coalesce(event_stamp, CompanyEvent.observed_at)
    return select(
        (literal("event_") + cast(CompanyEvent.id, String)).label("id"),
        func.jsonb_build_array(CompanyEvent.symbol).label("symbols"),
        cast(_event_sort_col(), String).label("published_at"),
        func.concat(CompanyEvent.symbol, literal(" · "), func.coalesce(CompanyEvent.event_name, CompanyEvent.event_type)).label("title"),
        cast(CompanyEvent.note, String).label("summary"),
        CompanyEvent.event_class.label("category"),
        literal("company_event").label("content_type"),
        CompanyEvent.source.label("source"), CompanyEvent.url.label("source_url"),
        CompanyEvent.event_class.label("ev_class"), CompanyEvent.event_type.label("ev_type"),
        stamp.label("sort_ts"),
        case(
            (CompanyEvent.ex_date.is_not(None), "ex_date"),
            (CompanyEvent.public_date.is_not(None), "public_date"),
            (CompanyEvent.record_date.is_not(None), "record_date"),
            (CompanyEvent.disclosure_date.is_not(None), "disclosure_date"),
            else_="observed",
        ).label("date_kind"),
    )


def _matches_query(query: str, *columns):
    # Literal tokens: SQL wildcards in user input do not broaden the search.
    return and_(*(or_(*(func.lower(c).contains(token, autoescape=True) for c in columns))
                  for token in query.lower().split()))


async def feed_symbol_facets(session: AsyncSession, *, lang: str = "vi") -> list[str]:
    news = select(func.jsonb_array_elements_text(ExternalNews.symbols).label("symbol")).where(ExternalNews.lang == lang)
    events = select(CompanyEvent.symbol.label("symbol"))
    union = news.union(events).subquery()
    stmt = select(union.c.symbol).where(union.c.symbol.is_not(None)).order_by(union.c.symbol)
    return list((await session.execute(stmt)).scalars().all())


async def list_feed(
    session: AsyncSession, *, symbol: str | None = None, symbols: list[str] | None = None,
    source: str | None = None, content_type: str | None = None, category: str | None = None,
    event_class: str | None = None, query: str | None = None, lang: str = "vi", limit: int = 30,
    before: str | None = None, cursor: str | None = None, date_from: date | None = None,
    date_to: date | None = None,
) -> tuple[list[FeedRow], bool]:
    """Filter in SQL, then paginate by (timestamp, ID); no upstream reads."""
    limit = max(1, min(int(limit), _MAX_LIMIT))
    want_news = content_type in (None, "exchange_disclosure") and source not in ("SSI", "VNDIRECT")
    want_events = content_type in (None, "company_event") and source != "HOSE"
    selected = [s.upper() for s in symbols] if symbols is not None else None
    selects = []
    if want_news:
        ns = _news_feed_select(lang)
        if symbol:
            ns = ns.where(ExternalNews.symbols.contains([symbol.upper()]))
        if selected is not None:
            ns = ns.where(ExternalNews.symbols.has_any(array(selected)) if selected else literal(False))
        if source:
            ns = ns.where(ExternalNews.source == source)
        if category:
            ns = ns.where(ExternalNews.category == category)
        if query and query.strip():
            ns = ns.where(_matches_query(query, ExternalNews.title, ExternalNews.summary_html,
                cast(ExternalNews.symbols, String), headline_search_label(ExternalNews.title, ExternalNews.category)))
        selects.append(ns)
    if want_events:
        es = _event_feed_select()
        if symbol:
            es = es.where(CompanyEvent.symbol == symbol.upper())
        if selected is not None:
            es = es.where(CompanyEvent.symbol.in_(selected))
        if source:
            es = es.where(CompanyEvent.source == source)
        if event_class:
            es = es.where(CompanyEvent.event_class == event_class.upper())
        if query and query.strip():
            es = es.where(_matches_query(query, CompanyEvent.symbol, CompanyEvent.note, CompanyEvent.event_name,
                event_search_label(CompanyEvent.event_class, CompanyEvent.event_type)))
        selects.append(es)
    if not selects:
        return [], False
    union = selects[0] if len(selects) == 1 else selects[0].union_all(*selects[1:])
    sub = union.subquery("feed")
    stmt = select(sub).order_by(desc(sub.c.sort_ts), desc(sub.c.id)).limit(limit + 1)
    local_day = cast(func.timezone("Asia/Ho_Chi_Minh", sub.c.sort_ts), Date)
    if date_from:
        stmt = stmt.where(local_day >= date_from)
    if date_to:
        stmt = stmt.where(local_day <= date_to)
    if cursor:
        stamp, ident = decode_feed_cursor(cursor)
        stmt = stmt.where(or_(sub.c.sort_ts < stamp, and_(sub.c.sort_ts == stamp, sub.c.id < ident)))
    elif before:
        stamp = datetime.fromisoformat(before.replace("Z", "+00:00"))
        stmt = stmt.where(sub.c.sort_ts < (stamp if stamp.tzinfo else stamp.replace(tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))))
    elif not symbol and selected is None and not date_from and not date_to:
        horizon = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date() + timedelta(days=14)
        stmt = stmt.where(local_day <= horizon)
    rows = (await session.execute(stmt)).mappings().all()
    has_more = len(rows) > limit
    result = []
    for m in rows[:limit]:
        syms = m["symbols"] or []
        stamp = m["sort_ts"]
        result.append(FeedRow(
            id=m["id"], symbol=syms[0] if syms else None, published_at=m["published_at"],
            title=m["title"], summary=m["summary"], category=m["category"],
            content_type=m["content_type"], source=m["source"], source_url=m["source_url"],
            ev_class=m["ev_class"], ev_type=m["ev_type"], _sort=stamp,
            display_date=stamp.isoformat() if stamp else None, date_kind=m["date_kind"],
        ))
    return result, has_more
