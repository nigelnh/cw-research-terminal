"""DATABASE_URL driver-scheme coercion.

Managed Postgres providers (Railway, Heroku, Render, Fly, ...) hand out a bare
``postgresql://`` URL. The async engine needs ``+asyncpg`` and Alembic needs
``+psycopg2``; both helpers must normalise every spelling in either direction.
"""

from __future__ import annotations

import pytest

from app.core.config import settings


@pytest.mark.parametrize(
    "given, sync_expected, async_expected",
    [
        (
            "postgresql://u:p@host:5432/db",
            "postgresql+psycopg2://u:p@host:5432/db",
            "postgresql+asyncpg://u:p@host:5432/db",
        ),
        (
            "postgres://u:p@host:5432/db",
            "postgresql+psycopg2://u:p@host:5432/db",
            "postgresql+asyncpg://u:p@host:5432/db",
        ),
        (
            "postgresql+asyncpg://u:p@host:5432/db",
            "postgresql+psycopg2://u:p@host:5432/db",
            "postgresql+asyncpg://u:p@host:5432/db",
        ),
        (
            "postgresql+psycopg2://u:p@host:5432/db",
            "postgresql+psycopg2://u:p@host:5432/db",
            "postgresql+asyncpg://u:p@host:5432/db",
        ),
    ],
)
def test_database_url_scheme_coercion(monkeypatch, given, sync_expected, async_expected):
    monkeypatch.setattr(settings, "DATABASE_URL", given)
    assert settings.sync_database_url() == sync_expected
    assert settings.async_database_url() == async_expected


def test_password_with_at_sign_is_preserved(monkeypatch):
    # only the scheme prefix is rewritten; the rest of the URL is untouched
    monkeypatch.setattr(settings, "DATABASE_URL", "postgresql://u:p%40ss@host:5432/db")
    assert settings.async_database_url() == "postgresql+asyncpg://u:p%40ss@host:5432/db"
