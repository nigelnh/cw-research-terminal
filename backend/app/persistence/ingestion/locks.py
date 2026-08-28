"""PostgreSQL advisory-lock coordination so two ingestion processes never work the same
logical stream (source + instrument + timeframe + price_basis) at the same time.

Session-level advisory locks (``pg_try_advisory_lock`` / ``pg_advisory_unlock``) are held
on a dedicated connection for the lifetime of a :class:`StreamLock` context. No Redis.
"""

from __future__ import annotations

import logging
import zlib
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import settings

logger = logging.getLogger(__name__)

_INT4_MIN = -(2**31)
_INT4_MAX = 2**31 - 1


def stream_lock_keys(source: str, instrument_id: int, timeframe: str, price_basis: str) -> tuple[int, int]:
    """Deterministic ``(classid, objid)`` int4 pair for one logical stream."""
    classid = int(settings.INGEST_ADVISORY_LOCK_NAMESPACE)
    if not (_INT4_MIN <= classid <= _INT4_MAX):
        classid = (classid & 0xFFFFFFFF) - (0x100000000 if classid & 0x80000000 else 0)
    raw = f"{source}:{instrument_id}:{timeframe}:{price_basis}".encode()
    unsigned = zlib.crc32(raw) & 0xFFFFFFFF
    objid = unsigned - 0x100000000 if unsigned & 0x80000000 else unsigned
    return classid, objid


class LockNotAcquired(RuntimeError):
    """Raised (or signalled) when another process already holds the stream lock."""


@asynccontextmanager
async def stream_lock(
    engine: AsyncEngine,
    *,
    source: str,
    instrument_id: int,
    timeframe: str,
    price_basis: str,
    wait: bool = False,
) -> AsyncIterator[bool]:
    """Acquire the advisory lock for one logical stream.

    Yields ``True`` if acquired, ``False`` if not (only possible when ``wait=False``).
    The lock is always released on exit, even on error, and the dedicated connection is
    returned to the pool.
    """
    classid, objid = stream_lock_keys(source, instrument_id, timeframe, price_basis)
    conn = await engine.connect()
    acquired = False
    try:
        if wait:
            await conn.execute(text("SELECT pg_advisory_lock(:c, :o)"), {"c": classid, "o": objid})
            acquired = True
        else:
            row = await conn.execute(text("SELECT pg_try_advisory_lock(:c, :o)"), {"c": classid, "o": objid})
            acquired = bool(row.scalar_one())
        if not acquired:
            logger.info(
                "stream lock busy: %s instrument=%s %s/%s already being ingested elsewhere",
                source, instrument_id, timeframe, price_basis,
            )
        yield acquired
    finally:
        if acquired:
            try:
                await conn.execute(text("SELECT pg_advisory_unlock(:c, :o)"), {"c": classid, "o": objid})
            except Exception as exc:  # noqa: BLE001
                logger.warning("failed to release advisory lock (%s,%s): %s", classid, objid, exc)
        await conn.close()
