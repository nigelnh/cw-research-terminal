"""Real, disposable PostgreSQL for the persistence integration tests.

We deliberately do NOT use SQLite: this layer relies on PostgreSQL-specific behavior
(``INSERT ... ON CONFLICT DO UPDATE``, ``xmax`` insert/update detection, ``JSONB``,
``NUMERIC`` exactness, partial-transaction rollback, identity columns).

A temporary cluster is created with the local ``initdb`` / ``pg_ctl`` binaries, started on
a private unix socket, migrated with ``alembic upgrade head``, and torn down at the end of
the session. If no PostgreSQL server binaries are found the whole package is skipped with
a clear message (set ``CW_PG_BIN=/path/to/postgres/bin`` to point at them).

The cluster fixture is synchronous (subprocess only). Async engines/sessions are created
per-test so we never fight pytest-asyncio over event-loop scope.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import psycopg2
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_BACKEND_DIR = Path(__file__).resolve().parents[2]

_CANDIDATE_BIN_DIRS = [
    os.environ.get("CW_PG_BIN", ""),
    "/opt/homebrew/opt/postgresql@16/bin",
    "/opt/homebrew/opt/postgresql@15/bin",
    "/opt/homebrew/opt/postgresql@14/bin",
    "/usr/lib/postgresql/16/bin",
    "/usr/lib/postgresql/15/bin",
    "/usr/local/opt/postgresql/bin",
]

_ALL_TABLES = (
    "market_bars",
    "instrument_snapshots",
    "ingestion_state",
    "ingestion_runs",
    "instruments",
    "user_watchlist_items",
    "user_watchlists",
    "external_news",
    "company_events",
    "company_profiles",
    "source_fetch_log",
)


def _find_pg_bin() -> Path | None:
    for d in _CANDIDATE_BIN_DIRS:
        if d and (Path(d) / "initdb").exists() and (Path(d) / "pg_ctl").exists():
            return Path(d)
    initdb = shutil.which("initdb")
    pg_ctl = shutil.which("pg_ctl")
    if initdb and pg_ctl:
        return Path(initdb).parent
    return None


_PG_BIN = _find_pg_bin()


@pytest.fixture(scope="session")
def pg_cluster() -> Iterator[dict]:
    if _PG_BIN is None:
        pytest.skip(
            "no local PostgreSQL server binaries (initdb/pg_ctl) found; "
            "set CW_PG_BIN to run persistence integration tests"
        )

    tmp = Path(tempfile.mkdtemp(prefix="cw_pg_test_"))
    data_dir = tmp / "data"
    sock_dir = tmp / "sock"
    sock_dir.mkdir()
    db_name = "cw_test"

    log_file = tmp / "postgres.log"
    subprocess.run(
        [str(_PG_BIN / "initdb"), "-D", str(data_dir), "-U", "postgres",
         "--auth=trust", "-E", "UTF8", "--no-sync"],
        check=True, capture_output=True, timeout=60,
    )
    # NOTE: use `-l <logfile>` so the postmaster does NOT inherit our stdout/stderr pipe -
    # otherwise `subprocess` blocks forever waiting for EOF on a pipe the daemon holds open.
    subprocess.run(
        [str(_PG_BIN / "pg_ctl"), "-D", str(data_dir), "-w", "-l", str(log_file), "start",
         "-o", f"-c listen_addresses= -c unix_socket_directories={sock_dir} "
               f"-c fsync=off -c full_page_writes=off -c synchronous_commit=off"],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60,
    )
    try:
        subprocess.run(
            [str(_PG_BIN / "createdb"), "-h", str(sock_dir), "-U", "postgres", db_name],
            check=True, capture_output=True, timeout=30,
        )
        async_url = f"postgresql+asyncpg://postgres@/{db_name}?host={sock_dir}"
        sync_url = f"postgresql+psycopg2://postgres@/{db_name}?host={sock_dir}"
        psycopg2_dsn = f"host={sock_dir} dbname={db_name} user=postgres"

        # Schema comes from the real migrations, never metadata.create_all.
        from alembic import command
        from alembic.config import Config

        alembic_cfg = Config(str(_BACKEND_DIR / "alembic.ini"))
        alembic_cfg.set_main_option("script_location", str(_BACKEND_DIR / "alembic"))
        _prev = os.environ.get("ALEMBIC_DATABASE_URL")
        os.environ["ALEMBIC_DATABASE_URL"] = sync_url
        try:
            command.upgrade(alembic_cfg, "head")
        finally:
            if _prev is None:
                os.environ.pop("ALEMBIC_DATABASE_URL", None)
            else:
                os.environ["ALEMBIC_DATABASE_URL"] = _prev

        yield {
            "async_url": async_url,
            "sync_url": sync_url,
            "psycopg2_dsn": psycopg2_dsn,
            "alembic_cfg": alembic_cfg,
            "socket": str(sock_dir),
        }
    finally:
        subprocess.run(
            [str(_PG_BIN / "pg_ctl"), "-D", str(data_dir), "-w", "-m", "immediate", "stop"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30,
        )
        shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture(autouse=True)
def _truncate(pg_cluster: dict) -> Iterator[None]:
    """Every test starts from an empty, identity-reset schema."""
    conn = psycopg2.connect(pg_cluster["psycopg2_dsn"])
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(f"TRUNCATE {', '.join(_ALL_TABLES)} RESTART IDENTITY CASCADE")
    finally:
        conn.close()
    yield


@pytest_asyncio.fixture
async def engine(pg_cluster: dict):
    # Generous pool: concurrency tests fan out ~20 simultaneous sessions + advisory-lock
    # connections against this one engine.
    eng = create_async_engine(pg_cluster["async_url"], pool_size=25, max_overflow=25, pool_timeout=15)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest_asyncio.fixture
async def sessionmaker_(engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


@pytest_asyncio.fixture
async def db(sessionmaker_) -> AsyncIterator[AsyncSession]:
    """A session whose transaction the test controls (commit to persist)."""
    async with sessionmaker_() as session:
        yield session
