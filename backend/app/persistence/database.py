"""Async engine / session lifecycle for the PostgreSQL persistence layer.

This module owns exactly one process-wide :class:`AsyncEngine`, created lazily from
``settings`` (or explicitly for tests). Nothing here runs unless
``settings.DATABASE_ENABLED`` is true or a caller wires an engine in by hand, so the
default application boot and the existing test-suite are completely unaffected.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _build_connect_args() -> dict[str, Any]:
    connect_args: dict[str, Any] = {}
    timeout_ms = int(settings.DATABASE_STATEMENT_TIMEOUT_MS)
    if timeout_ms > 0:
        # asyncpg applies this as a server setting on every pooled connection.
        connect_args["server_settings"] = {"statement_timeout": str(timeout_ms)}
    return connect_args


def create_engine_from_url(
    url: str,
    *,
    echo: bool | None = None,
    pool_size: int | None = None,
    max_overflow: int | None = None,
) -> AsyncEngine:
    """Construct an :class:`AsyncEngine` for ``url`` (must be a ``+asyncpg`` URL)."""
    if "+asyncpg" not in url:
        raise ValueError(
            "persistence async engine requires a postgresql+asyncpg:// URL; "
            "got a driver this layer does not use"
        )
    return create_async_engine(
        url,
        echo=settings.DATABASE_ECHO_SQL if echo is None else echo,
        pool_pre_ping=True,
        pool_size=settings.DATABASE_POOL_SIZE if pool_size is None else pool_size,
        max_overflow=settings.DATABASE_MAX_OVERFLOW if max_overflow is None else max_overflow,
        pool_timeout=settings.DATABASE_POOL_TIMEOUT_SECONDS,
        pool_recycle=settings.DATABASE_POOL_RECYCLE_SECONDS,
        connect_args=_build_connect_args(),
    )


def configure(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Install ``engine`` as the process-wide engine and return its sessionmaker.

    Used by the app lifespan and by test fixtures. Idempotent-ish: replacing the engine
    disposes the previous one is the caller's responsibility (tests do this).
    """
    global _engine, _sessionmaker
    _engine = engine
    _sessionmaker = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    return _sessionmaker


async def init_engine() -> async_sessionmaker[AsyncSession]:
    """Create the engine from ``settings.DATABASE_URL`` if not already configured."""
    global _sessionmaker
    if _sessionmaker is not None:
        return _sessionmaker
    if not settings.DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set but the persistence layer was asked to initialize")
    return configure(create_engine_from_url(settings.DATABASE_URL))


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


def is_configured() -> bool:
    return _sessionmaker is not None


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:
        raise RuntimeError("persistence layer is not initialized; call init_engine()/configure() first")
    return _sessionmaker


def get_engine() -> AsyncEngine:
    if _engine is None:
        raise RuntimeError("persistence layer is not initialized; call init_engine()/configure() first")
    return _engine


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Transactional scope: commits on success, rolls back on exception, always closes."""
    maker = get_sessionmaker()
    session = maker()
    try:
        async with session.begin():
            yield session
    finally:
        await session.close()


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: a session whose transaction the caller manages explicitly."""
    maker = get_sessionmaker()
    async with maker() as session:
        yield session


async def ping() -> bool:
    """Round-trip ``SELECT 1``. Raises on failure."""
    from sqlalchemy import text

    maker = get_sessionmaker()
    async with maker() as session:
        await session.execute(text("SELECT 1"))
    return True


async def health() -> dict[str, Any]:
    """Sanitized health snapshot for ``/health``. Never raises."""
    if not settings.DATABASE_ENABLED:
        return {"enabled": False, "configured": False, "connected": False}
    if _sessionmaker is None or _engine is None:
        return {"enabled": True, "configured": False, "connected": False}
    connected = False
    try:
        connected = await ping()
    except Exception as exc:  # noqa: BLE001 - health probe must not throw
        logger.debug("persistence health ping failed: %s", exc)
    pool = _engine.pool
    stats: dict[str, Any] = {"enabled": True, "configured": True, "connected": connected}
    for attr in ("size", "checkedin", "checkedout", "overflow"):
        fn = getattr(pool, attr, None)
        if callable(fn):
            try:
                stats[f"pool_{attr}"] = fn()
            except Exception:  # noqa: BLE001
                pass
    return stats
