"""Resolve a client-supplied watchlist symbol to backend-canonical instrument facts.

The authenticated user owns watchlist *membership and order* (and an optional note) - NOT
financial instrument metadata. This resolver is the trust boundary: given only a symbol,
it derives ``instrument_type`` and every reference field from sources the backend controls,
and returns ``None`` for a symbol the project does not recognize (so the caller rejects it).

Resolution order:
  1. InstrumentRegistry - authoritative for covered-warrant contract terms
     (issuer, underlying, strike, ratio, maturity, last trading date). Includes
     PARTIAL / EXPIRED / UNKNOWN warrants - those legitimately exist and stay valid.
  2. PostgreSQL ``instruments`` table - for stocks / indices that have been seeded.
  3. Curated HOSE equity allow-list (``instrument_refresh.VN_UNDERLYINGS``) + the registry's
     own set of covered-warrant underlyings - recognized equities that are not CWs.
  4. Curated index allow-list (``seed.KNOWN_INDICES``).
  5. otherwise -> ``None`` (unknown symbol).

Client-supplied instrument_type / underlying / issuer / strike / ratio / dates are never
read here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.instruments.instrument_refresh import VN_UNDERLYINGS
from app.instruments.instrument_registry import InstrumentRegistry, instrument_registry
from app.persistence.ingestion.seed import KNOWN_INDICES
from app.persistence.repositories.instrument_repository import InstrumentRepository

_KNOWN_INDEX_SYMBOLS = frozenset(sym.upper() for sym, _exchange in KNOWN_INDICES)
_KNOWN_EQUITY_SYMBOLS = frozenset(s.strip().upper() for s in VN_UNDERLYINGS)


@dataclass(frozen=True, slots=True)
class ResolvedInstrument:
    symbol: str
    instrument_type: str  # "CW" | "STOCK" | "INDEX"
    underlying_symbol: str | None = None
    issuer: str | None = None
    strike_price: float | None = None
    exercise_ratio: float | None = None
    maturity_date: date | None = None
    last_trading_date: date | None = None
    data_quality: str | None = None  # COMPLETE | PARTIAL | None (observability only)


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


class InstrumentResolver:
    """Stateless apart from the (optional) DB session it reads through."""

    def __init__(
        self,
        session: AsyncSession | None = None,
        registry: InstrumentRegistry | None = None,
    ) -> None:
        self._session = session
        self._registry = registry or instrument_registry

    async def resolve(self, symbol: str) -> ResolvedInstrument | None:
        sym = (symbol or "").strip().upper()
        if not (1 <= len(sym) <= 32) or not sym.replace(".", "").isalnum():
            return None

        # 1. Covered warrant - registry owns the contract terms.
        cw = await self._registry.get_instrument(sym)
        if cw is not None:
            return ResolvedInstrument(
                symbol=sym,
                instrument_type="CW",
                underlying_symbol=(cw.underlying_symbol or None),
                issuer=(cw.issuer or None),
                strike_price=cw.effective_strike,
                exercise_ratio=cw.effective_ratio,
                maturity_date=_parse_iso_date(cw.maturity_date),
                last_trading_date=_parse_iso_date(cw.last_trading_date),
                data_quality=cw.data_quality.value if cw.data_quality else None,
            )

        # 2. Persisted instruments table (seeded stocks / indices).
        if self._session is not None:
            repo = InstrumentRepository(self._session)
            row = await repo.get_by_symbol(sym)
            if row is not None:
                underlying = None
                if row.underlying_instrument_id is not None:
                    parent = await repo.get_by_id(row.underlying_instrument_id)
                    underlying = parent.symbol if parent else None
                itype = row.instrument_type.strip().upper()
                return ResolvedInstrument(
                    symbol=sym,
                    instrument_type=itype if itype in ("CW", "STOCK", "INDEX") else "STOCK",
                    underlying_symbol=underlying,
                    issuer=(row.metadata or {}).get("issuer"),
                )

        # 3. Recognized equity (CW underlying or curated HOSE list).
        underlyings = set(await self._registry.get_underlyings(active_only=False))
        if sym in underlyings or sym in _KNOWN_EQUITY_SYMBOLS:
            return ResolvedInstrument(symbol=sym, instrument_type="STOCK")

        # 4. Curated HOSE / HNX index.
        if sym in _KNOWN_INDEX_SYMBOLS:
            return ResolvedInstrument(symbol=sym, instrument_type="INDEX")

        return None
