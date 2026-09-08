"""Command-line entry point for historical ingestion.

    python -m app.persistence.cli seed-instruments
    python -m app.persistence.cli backfill --symbols HPG,FPT --timeframe 1D --from 2025-01-01 --to 2026-08-01 --adjusted --dry-run
    python -m app.persistence.cli incremental --symbols HPG,FPT --timeframe 1D --adjusted
    python -m app.persistence.cli gaps --symbol HPG --timeframe 1D --adjusted
    python -m app.persistence.cli repair --symbol HPG --timeframe 1D --adjusted --from 2025-01-01 --to 2026-08-01
    python -m app.persistence.cli status --symbols HPG,FPT --timeframe 1D --adjusted
    python -m app.persistence.cli recent-runs

Only ``backfill``/``incremental``/``repair`` (without ``--dry-run``) and ``gaps``/``status``
touch FiinQuant or the database. Ingestion uses the historical SDK path only - never a
SignalR stream.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import date, datetime

from app.core.config import settings

logger = logging.getLogger("app.persistence.cli")


# --------------------------------------------------------------------------- #
# argument helpers
# --------------------------------------------------------------------------- #
def _parse_date(s: str) -> date:
    return datetime.strptime(s.strip(), "%Y-%m-%d").date()


def _split_symbols(s: str) -> list[str]:
    return [tok.strip().upper() for tok in s.replace(" ", ",").split(",") if tok.strip()]


def _add_basis(p: argparse.ArgumentParser) -> None:
    g = p.add_mutually_exclusive_group()
    g.add_argument("--adjusted", dest="adjusted", action="store_true", help="corporate-action-adjusted series (stocks/indices)")
    g.add_argument("--raw", dest="adjusted", action="store_false", help="as-traded series (required for covered warrants)")
    p.set_defaults(adjusted=True)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m app.persistence.cli", description=__doc__)
    p.add_argument("--database-url", default=None, help="override DATABASE_URL (postgresql+asyncpg://...)")
    p.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("seed-instruments", help="seed the instruments table from the InstrumentRegistry")

    bf = sub.add_parser("backfill", help="bounded historical backfill into PostgreSQL")
    bf.add_argument("--symbols", required=True, type=_split_symbols)
    bf.add_argument("--timeframe", default="1D")
    bf.add_argument("--from", dest="from_date", required=True, type=_parse_date)
    bf.add_argument("--to", dest="to_date", default=None, type=_parse_date)
    bf.add_argument("--concurrency", type=int, default=None)
    bf.add_argument("--dry-run", action="store_true")
    bf.add_argument("--force", action="store_true", help="re-fetch chunks already covered per the cursor")
    bf.add_argument("--include-forming", action="store_true", help="also persist the still-forming current bar")
    _add_basis(bf)

    inc = sub.add_parser("incremental", help="fetch only the missing tail since the last persisted bar")
    inc.add_argument("--symbols", required=True, type=_split_symbols)
    inc.add_argument("--timeframe", default="1D")
    inc.add_argument("--concurrency", type=int, default=None)
    inc.add_argument("--dry-run", action="store_true")
    inc.add_argument("--include-forming", action="store_true")
    _add_basis(inc)

    gp = sub.add_parser("gaps", help="conservative gap detection over a range")
    gp.add_argument("--symbol", required=True)
    gp.add_argument("--timeframe", default="1D")
    gp.add_argument("--from", dest="from_date", default=None, type=_parse_date)
    gp.add_argument("--to", dest="to_date", default=None, type=_parse_date)
    _add_basis(gp)

    rp = sub.add_parser("repair", help="re-fetch only missing/suspicious portions of a range")
    rp.add_argument("--symbol", required=True)
    rp.add_argument("--timeframe", default="1D")
    rp.add_argument("--from", dest="from_date", required=True, type=_parse_date)
    rp.add_argument("--to", dest="to_date", default=None, type=_parse_date)
    rp.add_argument("--include-unknown", action="store_true", help="also attempt UNKNOWN_CALENDAR segments")
    rp.add_argument("--dry-run", action="store_true")
    _add_basis(rp)

    st = sub.add_parser("status", help="persisted coverage + cursor for symbols")
    st.add_argument("--symbols", required=True, type=_split_symbols)
    st.add_argument("--timeframe", default="1D")
    _add_basis(st)

    rr = sub.add_parser("recent-runs", help="recent ingestion_runs")
    rr.add_argument("--limit", type=int, default=15)

    return p


# --------------------------------------------------------------------------- #
# wiring
# --------------------------------------------------------------------------- #
def _resolve_db_url(args) -> str:
    url = args.database_url or settings.DATABASE_URL
    if not url:
        print(
            "error: no database URL. Set DATABASE_URL (postgresql+asyncpg://...) in the "
            "environment / backend/.env, or pass --database-url.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    if "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://").replace("postgres://", "postgresql+asyncpg://")
    return url


async def _make_service(args):
    from app.persistence import database as db
    from app.market_data.providers.provider_factory import create_market_provider
    from app.persistence.ingestion.retry import RetryPolicy
    from app.persistence.ingestion.service import IngestionService

    engine = db.create_engine_from_url(_resolve_db_url(args))
    sm = db.configure(engine)
    provider = create_market_provider()  # historical adapter; live pollers are never started
    service = IngestionService(
        engine=engine, sessionmaker=sm, bar_provider=provider, retry_policy=RetryPolicy.from_settings()
    )
    return engine, service


def _emit(args, payload) -> None:
    if args.json:
        print(json.dumps(payload, indent=2, default=str))
    else:
        _pretty(args.command, payload)


def _pretty(command: str, payload) -> None:  # noqa: C901 - flat dispatch
    if command in ("backfill", "incremental"):
        print(f"run_id={payload['run_id']}  operation={payload['operation']}  status={payload['status']}")
        f, i, u = payload["totals"]
        print(f"totals: fetched={f} inserted={i} updated={u}")
        for s in payload["streams"]:
            line = f"  {s['symbol']:10} {s['timeframe']:>3}/{s['price_basis']:<8} {s['status']}"
            if s.get("clamp_note"):
                line += f"  [CLAMPED] {s['clamp_note']}"
            print(line)
            for c in s["chunks"]:
                extra = f" err={c['error']}" if c.get("error") else ""
                print(
                    f"      #{c['seq']:<2} {c['start']}..{c['end']}  {c['status']:<14}"
                    f" fetched={c['fetched']} ins={c['inserted']} upd={c['updated']}"
                    f" dropped_incomplete={c['dropped_incomplete']} attempts={c['attempts']}{extra}"
                )
    elif command == "seed-instruments":
        print(json.dumps(payload, indent=2, default=str))
    elif command == "gaps":
        print(f"{payload['symbol']} {payload['timeframe']}/{payload['price_basis']}  "
              f"scan {payload['scan_start']}..{payload['scan_end']}  seeded={payload['seeded']}")
        print(f"  bars={payload['bar_count']} expected_sessions={payload['expected_sessions']} "
              f"present={payload['present_sessions']}")
        for seg in payload["segments"]:
            print(f"  {seg['classification']:<16} {seg['start']}..{seg['end']} ({seg['missing_days']}d)")
        if not payload["segments"]:
            print("  no gaps")
    elif command == "repair":
        print(json.dumps(payload, indent=2, default=str))
    elif command == "status":
        for row in payload:
            if not row.get("seeded"):
                print(f"  {row['symbol']:10} NOT SEEDED")
                continue
            print(f"  {row['symbol']:10} {row['timeframe']}/{row['price_basis']:<8} "
                  f"bars={row['bar_count']:<6} {row['earliest']} .. {row['latest']}  "
                  f"cursor={row['cursor_last_bar_ts']}")
    elif command == "recent-runs":
        for r in payload:
            print(f"  #{r['id']:<5} {r['status']:<10} {r['operation'] if 'operation' in r else ''} "
                  f"{r['timeframe']}/{r['price_basis']:<8} "
                  f"fetched={r['rows_fetched']} ins={r['rows_inserted']} upd={r['rows_updated']} "
                  f"{r['started_at']}")
            if r.get("error_summary"):
                print(f"       {r['error_summary']}")
    else:
        print(json.dumps(payload, indent=2, default=str))


# --------------------------------------------------------------------------- #
# command handlers
# --------------------------------------------------------------------------- #
async def _cmd_seed(args) -> int:
    from app.persistence import database as db
    from app.persistence.ingestion.seed import seed_instruments

    engine = db.create_engine_from_url(_resolve_db_url(args))
    db.configure(engine)
    try:
        report = await seed_instruments()
        _emit(args, {
            "stocks_seeded": report.stocks_seeded, "indices_seeded": report.indices_seeded,
            "warrants_seeded": report.warrants_seeded, "total": report.total,
            "active": report.active_count, "inactive": report.inactive_count,
            "underlyings_resolved": report.underlyings_resolved,
            "warrants_unresolved_underlying": report.warrants_unresolved_underlying,
        })
        return 0
    finally:
        await engine.dispose()


def _result_payload(res) -> dict:
    return {
        "run_id": res.run_id, "operation": res.operation, "status": res.status,
        "timeframe": res.timeframe, "price_basis": res.price_basis, "dry_run": res.dry_run,
        "totals": list(res.totals()),
        "streams": [
            {
                "symbol": s.symbol, "instrument_type": s.instrument_type, "timeframe": s.timeframe,
                "price_basis": s.price_basis, "status": s.status, "lookback_clamped": s.lookback_clamped,
                "clamp_note": s.clamp_note, "error": s.error, "fetched": s.fetched,
                "inserted": s.inserted, "updated": s.updated,
                "chunks": [vars(c) for c in s.chunks],
            }
            for s in res.streams
        ],
    }


async def _cmd_backfill(args) -> int:
    engine, service = await _make_service(args)
    try:
        res = await service.backfill(
            args.symbols, timeframe=args.timeframe, adjusted=args.adjusted,
            from_date=args.from_date, to_date=args.to_date or date.today(),
            concurrency=args.concurrency, dry_run=args.dry_run, force=args.force,
            include_forming=args.include_forming,
        )
        _emit(args, _result_payload(res))
        return 0 if res.status in ("SUCCEEDED", "DRY_RUN", "LOCKED_SKIPPED") else 1
    finally:
        await engine.dispose()


async def _cmd_incremental(args) -> int:
    engine, service = await _make_service(args)
    try:
        res = await service.incremental(
            args.symbols, timeframe=args.timeframe, adjusted=args.adjusted,
            concurrency=args.concurrency, dry_run=args.dry_run, include_forming=args.include_forming,
        )
        _emit(args, _result_payload(res))
        return 0 if res.status in ("SUCCEEDED", "DRY_RUN", "LOCKED_SKIPPED") else 1
    finally:
        await engine.dispose()


async def _cmd_gaps(args) -> int:
    engine, service = await _make_service(args)
    try:
        from app.persistence.ingestion.gaps import detect_gaps

        frm = args.from_date or (date.today().replace(year=date.today().year - 1))
        to = args.to_date or date.today()
        report = await detect_gaps(
            service, symbol=args.symbol, timeframe=args.timeframe, adjusted=args.adjusted,
            from_date=frm, to_date=to,
        )
        _emit(args, report.as_dict())
        return 0
    finally:
        await engine.dispose()


async def _cmd_repair(args) -> int:
    engine, service = await _make_service(args)
    try:
        from app.persistence.ingestion.gaps import repair_gaps

        result = await repair_gaps(
            service, symbol=args.symbol, timeframe=args.timeframe, adjusted=args.adjusted,
            from_date=args.from_date, to_date=args.to_date or date.today(),
            include_unknown=args.include_unknown, dry_run=args.dry_run,
        )
        _emit(args, result.as_dict())
        return 0
    finally:
        await engine.dispose()


async def _cmd_status(args) -> int:
    engine, service = await _make_service(args)
    try:
        rows = await service.status(args.symbols, timeframe=args.timeframe, adjusted=args.adjusted)
        _emit(args, rows)
        return 0
    finally:
        await engine.dispose()


async def _cmd_recent_runs(args) -> int:
    from app.persistence import database as db
    from app.persistence.repositories.ingestion_repository import IngestionRepository

    engine = db.create_engine_from_url(_resolve_db_url(args))
    sm = db.configure(engine)
    try:
        async with sm() as session:
            runs = await IngestionRepository(session).recent_runs(limit=args.limit)
        _emit(args, [
            {
                "id": r.id, "status": r.status, "timeframe": r.timeframe, "price_basis": r.price_basis,
                "rows_fetched": r.rows_fetched, "rows_inserted": r.rows_inserted, "rows_updated": r.rows_updated,
                "started_at": r.started_at, "completed_at": r.completed_at, "error_summary": r.error_summary,
            }
            for r in runs
        ])
        return 0
    finally:
        await engine.dispose()


_HANDLERS = {
    "seed-instruments": _cmd_seed,
    "backfill": _cmd_backfill,
    "incremental": _cmd_incremental,
    "gaps": _cmd_gaps,
    "repair": _cmd_repair,
    "status": _cmd_status,
    "recent-runs": _cmd_recent_runs,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    try:
        return asyncio.run(_HANDLERS[args.command](args))
    except KeyboardInterrupt:
        print("\ninterrupted - persisted bars and ingestion_state are durable; rerun to resume.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
