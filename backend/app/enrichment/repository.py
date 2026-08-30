"""Read-only PostgreSQL access for the enrichment domains.

These functions NEVER contact an upstream source. If the table is empty they return an
empty result — the API layer turns that into a truthful empty state, not an error.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.persistence.models import CompanyProfile, CorporateAction, ExternalNews

_MAX_LIMIT = 100


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


async def list_corporate_actions(
    session: AsyncSession,
    *,
    symbol: str,
    limit: int = 20,
    action_types: list[str] | None = None,
) -> list[CorporateAction]:
    limit = max(1, min(int(limit), _MAX_LIMIT))
    stmt = select(CorporateAction).where(CorporateAction.symbol == symbol.upper())
    if action_types:
        stmt = stmt.where(CorporateAction.action_type.in_(action_types))
    stmt = stmt.order_by(
        desc(
            func.coalesce(
                CorporateAction.ex_date,
                CorporateAction.record_date,
                CorporateAction.disclosure_date,
            )
        )
    ).limit(limit)
    return list((await session.execute(stmt)).scalars().all())


async def get_company_profile(session: AsyncSession, symbol: str) -> CompanyProfile | None:
    stmt = select(CompanyProfile).where(CompanyProfile.symbol == symbol.upper())
    return (await session.execute(stmt)).scalar_one_or_none()


async def news_count_for_symbol(session: AsyncSession, symbol: str, *, lang: str = "vi") -> int:
    stmt = (
        select(func.count())
        .select_from(ExternalNews)
        .where(and_(ExternalNews.lang == lang, ExternalNews.symbols.contains([symbol.upper()])))
    )
    return int((await session.execute(stmt)).scalar() or 0)
