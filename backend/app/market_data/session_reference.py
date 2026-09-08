"""Session-static reference price enrichment for the canonical realtime state."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Any

from app.market_data import trading_calendar as cal
from app.market_data.market_schemas import CanonicalQuote
from app.market_data.market_state import MarketState

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReferenceUpdate:
    symbol: str
    quote: CanonicalQuote
    diff: dict[str, Any]


def reference_session_date(now: datetime | None = None) -> date:
    """Session whose bands should be used now in ICT.

    The display rolls at 08:00 ICT on trading days, not at midnight. Weekends and
    holidays retain the last completed session. This is also the intraday reset boundary.
    """
    return cal.reference_session_date(now)


async def refresh_session_references(
    *,
    provider,
    state: MarketState,
    store,
    symbols: Iterable[str],
    session_date: date | None = None,
    now: datetime | None = None,
) -> list[ReferenceUpdate]:
    """Fetch, merge and enqueue Redis writes for static session price metadata.

    Failures are deliberately non-fatal: a missing optional reference endpoint must never
    prevent the live trade/book streams from starting. Callers can publish the returned
    diffs through their existing patch listeners.
    """
    clean = sorted({str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()})
    if not clean:
        return []
    target = session_date or reference_session_date(now)
    try:
        rows = await provider.get_session_reference_data(clean, target)
    except NotImplementedError:
        return []
    except Exception as exc:  # noqa: BLE001 - live stream must continue without enrichment
        logger.warning("Session reference refresh failed for %d symbols: %s", len(clean), exc)
        return []

    observed_ms = int((now or datetime.now(timezone.utc)).timestamp() * 1000)
    updates: list[ReferenceUpdate] = []
    for symbol in clean:
        row = rows.get(symbol)
        if not isinstance(row, dict) or row.get("session_date") != target.isoformat():
            continue
        quote, diff = state.apply_reference_metadata(
            symbol,
            session_date=target.isoformat(),
            reference_price=row.get("reference_price"),
            ceiling_price=row.get("ceiling_price"),
            floor_price=row.get("floor_price"),
            observed_timestamp=observed_ms,
        )
        if not diff:
            continue
        try:
            store.enqueue_save(symbol, quote)
        except Exception as exc:  # noqa: BLE001 - Redis is an optional warm cache
            logger.debug("Session reference Redis enqueue failed for %s: %s", symbol, exc)
        updates.append(ReferenceUpdate(symbol=symbol, quote=quote, diff=diff))
    return updates
