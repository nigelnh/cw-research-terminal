"""Alembic migration environment.

URL resolution order:
  1. ``-x db_url=postgresql+psycopg2://...`` passed on the command line
  2. ``ALEMBIC_DATABASE_URL`` environment variable
  3. ``settings.sync_database_url()`` (derived from ``DATABASE_URL``)

Migrations run through the synchronous psycopg2 driver even though the app uses asyncpg.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import settings
from app.persistence.models import Base

config = context.config

if config.config_file_name is not None:
    # Don't tear down loggers already configured by the host process (e.g. the test suite
    # or the FastAPI app when migrations are run in-process).
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _resolve_url() -> str:
    x_args = context.get_x_argument(as_dictionary=True)
    if x_args.get("db_url"):
        return x_args["db_url"]
    env_url = os.getenv("ALEMBIC_DATABASE_URL")
    if env_url:
        # accept either sync or async spelling
        return env_url.replace("+asyncpg", "+psycopg2")
    url = settings.sync_database_url()
    if not url:
        raise RuntimeError(
            "No database URL for Alembic. Set DATABASE_URL / ALEMBIC_DATABASE_URL "
            "or pass -x db_url=postgresql+psycopg2://..."
        )
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=_resolve_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = _resolve_url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
