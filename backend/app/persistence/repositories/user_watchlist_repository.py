"""Data access for the user-owned primary watchlist.

The central security invariant lives here: **every query is scoped to a single
``owner_subject``**, which the API layer sources exclusively from the verified JWT
(:class:`app.auth.CurrentUser`). This repository has no method that reads or writes a row
by primary key without an owner filter, and it never reads an owner id from anything a
client sent.

``replace_for_owner`` is a full transactional replace (delete-all + insert) so a partial
or malformed client payload can never leave a half-written list - either the whole new
ordered set commits or nothing does. The caller owns the transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.persistence.models import UserWatchlist, UserWatchlistItem
from app.persistence.rows import UserWatchlistItemRow, UserWatchlistRow

_VALID_TYPES = {"CW", "STOCK", "INDEX"}


class WatchlistValidationError(ValueError):
    """Structurally invalid item set (bad symbol, duplicate, over capacity)."""


@dataclass(frozen=True, slots=True)
class WatchlistItemInput:
    """One resolved item to persist.

    Only ``symbol`` (membership/order) and ``notes`` originate from the user. Every other
    field is backend-canonical - the API layer fills them from
    :class:`app.me.instrument_resolver.InstrumentResolver`, never from the request body.
    """

    symbol: str
    instrument_type: str
    underlying_symbol: str | None = None
    issuer: str | None = None
    strike_price: float | None = None
    exercise_ratio: float | None = None
    maturity_date: date | None = None
    last_trading_date: date | None = None
    notes: str | None = None


def _clean_subject(owner_subject: str) -> str:
    s = (owner_subject or "").strip()
    if not s:
        raise ValueError("owner_subject must be non-empty")
    return s


def _clean_symbol(symbol: str) -> str:
    s = (symbol or "").strip().upper()
    if not (3 <= len(s) <= 32) or not s.replace(".", "").isalnum():
        raise WatchlistValidationError(f"invalid symbol: {symbol!r}")
    return s


def _item_to_row(m: UserWatchlistItem) -> UserWatchlistItemRow:
    return UserWatchlistItemRow(
        symbol=m.symbol,
        instrument_type=m.instrument_type,
        position=m.position,
        underlying_symbol=m.underlying_symbol,
        issuer=m.issuer,
        strike_price=float(m.strike_price) if m.strike_price is not None else None,
        exercise_ratio=float(m.exercise_ratio) if m.exercise_ratio is not None else None,
        maturity_date=m.maturity_date,
        last_trading_date=m.last_trading_date,
        notes=m.notes,
    )


def _to_row(m: UserWatchlist) -> UserWatchlistRow:
    ordered = sorted(m.items, key=lambda it: (it.position, it.id or 0))
    return UserWatchlistRow(
        owner_subject=m.owner_subject,
        name=m.name,
        items=tuple(_item_to_row(it) for it in ordered),
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


class UserWatchlistRepository:
    """One instance per unit of work; the caller owns the transaction."""

    def __init__(self, session: AsyncSession, *, max_items: int = 50) -> None:
        self._session = session
        self._max_items = max(1, int(max_items))

    def _validate(self, items: list[WatchlistItemInput]) -> list[tuple[str, WatchlistItemInput]]:
        if len(items) > self._max_items:
            raise WatchlistValidationError(
                f"watchlist exceeds the maximum of {self._max_items} items"
            )
        seen: set[str] = set()
        cleaned: list[tuple[str, WatchlistItemInput]] = []
        for it in items:
            sym = _clean_symbol(it.symbol)
            itype = (it.instrument_type or "").strip().upper()
            if itype not in _VALID_TYPES:
                raise WatchlistValidationError(
                    f"instrument_type must be one of {sorted(_VALID_TYPES)}, got {it.instrument_type!r}"
                )
            if sym in seen:
                raise WatchlistValidationError(f"duplicate symbol: {sym}")
            seen.add(sym)
            cleaned.append((sym, it))
        return cleaned

    async def _load(self, owner_subject: str) -> UserWatchlist | None:
        stmt = select(UserWatchlist).where(UserWatchlist.owner_subject == owner_subject)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_for_owner(self, owner_subject: str) -> UserWatchlistRow | None:
        subj = _clean_subject(owner_subject)
        m = await self._load(subj)
        return _to_row(m) if m is not None else None

    async def replace_for_owner(
        self, owner_subject: str, items: list[WatchlistItemInput]
    ) -> UserWatchlistRow:
        subj = _clean_subject(owner_subject)
        cleaned = self._validate(items)

        wl = await self._load(subj)
        if wl is None:
            wl = UserWatchlist(owner_subject=subj, name="Primary Watchlist")
            self._session.add(wl)
            await self._session.flush()
        else:
            await self._session.execute(
                delete(UserWatchlistItem).where(UserWatchlistItem.watchlist_id == wl.id)
            )

        def _norm(value: str | None, *, upper: bool = False, limit: int | None = None) -> str | None:
            if value is None:
                return None
            s = value.strip()
            if not s:
                return None
            s = s.upper() if upper else s
            return s[:limit] if limit else s

        for position, (sym, it) in enumerate(cleaned):
            self._session.add(
                UserWatchlistItem(
                    watchlist_id=wl.id,
                    symbol=sym,
                    instrument_type=it.instrument_type.strip().upper(),
                    position=position,
                    underlying_symbol=_norm(it.underlying_symbol, upper=True),
                    issuer=_norm(it.issuer),
                    strike_price=it.strike_price,
                    exercise_ratio=it.exercise_ratio,
                    maturity_date=it.maturity_date,
                    last_trading_date=it.last_trading_date,
                    notes=_norm(it.notes, limit=500),
                )
            )

        await self._session.flush()
        wl.updated_at = datetime.now(timezone.utc)
        await self._session.flush()
        await self._session.refresh(wl, attribute_names=["items", "updated_at"])
        return _to_row(wl)
