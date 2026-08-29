"""Authenticated per-user watchlist API.

    GET  /api/me/watchlist   -> the caller's ordered primary watchlist (empty if none)
    PUT  /api/me/watchlist   -> atomically replace it with the supplied ordered list

Ownership: ``owner_subject = current_user.subject`` (verified JWT ``sub``), never the body.
Instrument metadata: resolved on the backend from the InstrumentRegistry / ``instruments``
table (see :class:`InstrumentResolver`) - never trusted from the client. A symbol the
project does not recognize is rejected with 400.

When auth is not configured -> 503 (auth dependency). When persistence is not
enabled/reachable -> 503 here. All normal auth failures -> 401 (never 500).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser, get_current_user
from app.core.config import settings
from app.me.instrument_resolver import InstrumentResolver
from app.me.me_schemas import WatchlistItemView, WatchlistPutRequest, WatchlistResponse
from app.persistence import database as persistence_db
from app.persistence.repositories import (
    UserWatchlistRepository,
    WatchlistItemInput,
    WatchlistValidationError,
)
from app.persistence.rows import UserWatchlistItemRow, UserWatchlistRow

logger = logging.getLogger("cw-research-backend.me")

me_router = APIRouter(prefix="/api/me", tags=["Me (authenticated)"])


async def _db_session() -> AsyncIterator[AsyncSession]:
    if not persistence_db.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "unavailable", "reason": "persistence_not_configured"},
        )
    maker = persistence_db.get_sessionmaker()
    async with maker() as session:
        yield session


def _to_view(it: UserWatchlistItemRow) -> WatchlistItemView:
    """Fallback view straight from the stored row (used only if live resolution fails)."""
    return WatchlistItemView(
        symbol=it.symbol,
        instrument_type=it.instrument_type,  # type: ignore[arg-type]
        underlying_symbol=it.underlying_symbol,
        issuer=it.issuer,
        strike_price=it.strike_price,
        exercise_ratio=it.exercise_ratio,
        maturity_date=it.maturity_date.isoformat() if it.maturity_date else None,
        last_trading_date=it.last_trading_date.isoformat() if it.last_trading_date else None,
        notes=it.notes,
    )


async def _resolved_view(it: UserWatchlistItemRow, resolver: InstrumentResolver) -> WatchlistItemView:
    """Contract metadata is re-resolved from the canonical registry on every read, so a
    later correction (e.g. a fixed strike/ratio/issuer) is reflected without the user
    re-adding the symbol. The stored row keeps only identity + preference authority."""
    r = await resolver.resolve(it.symbol)
    if r is None:
        return _to_view(it)
    return WatchlistItemView(
        symbol=it.symbol,
        instrument_type=r.instrument_type,  # type: ignore[arg-type]
        underlying_symbol=r.underlying_symbol,
        issuer=r.issuer,
        strike_price=r.strike_price,
        exercise_ratio=r.exercise_ratio,
        maturity_date=r.maturity_date.isoformat() if r.maturity_date else None,
        last_trading_date=r.last_trading_date.isoformat() if r.last_trading_date else None,
        data_quality=r.data_quality,
        metadata_verification=r.metadata_verification,
        notes=it.notes,
    )


async def _to_response(row: UserWatchlistRow | None, resolver: InstrumentResolver) -> WatchlistResponse:
    if row is None:
        return WatchlistResponse(items=[], updated_at=None)
    items = [await _resolved_view(it, resolver) for it in row.items]
    return WatchlistResponse(
        items=items,
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
    )


@me_router.get("/watchlist", response_model=WatchlistResponse)
async def get_my_watchlist(
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(_db_session),
) -> WatchlistResponse:
    repo = UserWatchlistRepository(session, max_items=settings.ME_WATCHLIST_MAX_ITEMS)
    row = await repo.get_for_owner(user.subject)
    return await _to_response(row, InstrumentResolver(session))


@me_router.put("/watchlist", response_model=WatchlistResponse)
async def put_my_watchlist(
    payload: WatchlistPutRequest,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(_db_session),
) -> WatchlistResponse:
    max_items = settings.ME_WATCHLIST_MAX_ITEMS
    # Capacity guard first, so an over-long list fails cheaply (before any resolution).
    if len(payload.items) > max_items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_watchlist", "reason": f"watchlist exceeds the maximum of {max_items} items"},
        )

    try:
        async with session.begin():
            resolver = InstrumentResolver(session)
            resolved: list[WatchlistItemInput] = []
            for item in payload.items:
                canonical = await resolver.resolve(item.symbol)
                if canonical is None:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail={
                            "error": "invalid_watchlist",
                            "reason": f"unknown instrument: {item.symbol.strip().upper()}",
                        },
                    )
                resolved.append(
                    WatchlistItemInput(
                        symbol=canonical.symbol,
                        instrument_type=canonical.instrument_type,
                        underlying_symbol=canonical.underlying_symbol,
                        issuer=canonical.issuer,
                        strike_price=canonical.strike_price,
                        exercise_ratio=canonical.exercise_ratio,
                        maturity_date=canonical.maturity_date,
                        last_trading_date=canonical.last_trading_date,
                        notes=item.notes,  # the ONLY client-authored field
                    )
                )
            repo = UserWatchlistRepository(session, max_items=max_items)
            row = await repo.replace_for_owner(user.subject, resolved)
    except WatchlistValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_watchlist", "reason": str(exc)},
        ) from exc

    logger.info("watchlist replaced for subject=%s (%d items)", user.subject, len(row.items))
    return await _to_response(row, InstrumentResolver(session))
