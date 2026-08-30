"""Command-line entrypoints for Step 14A research enrichment ingestion.

    python -m app.enrichment.cli news --days 30 --lang vi
    python -m app.enrichment.cli news --start 2026-08-01 --end 2026-08-31 --lang vi --lang en
    python -m app.enrichment.cli corporate-actions --symbols HPG,VPB,TCB
    python -m app.enrichment.cli company-profiles --symbols HPG,VPB,TCB
    python -m app.enrichment.cli validate-history --symbols HPG,VPB,TCB,VHM --days 30
    python -m app.enrichment.cli bootstrap        # curated universe + 30d news window
    python -m app.enrichment.cli status

Only ``news`` / ``corporate-actions`` / ``company-profiles`` / ``bootstrap`` write to the
database (and hit an external source). ``validate-history`` reads production canonical
history over the public API and compares — it never writes. There is no scheduler; run
these manually or wire them into a job runner later.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import date, datetime, timedelta

from app.core.config import settings

logger = logging.getLogger("app.enrichment.cli")

# Curated bootstrap universe: default research/demo set + active-CW underlyings + a few
# high-liquidity blue chips that back most HOSE covered warrants.
BOOTSTRAP_SYMBOLS = [
    "HPG", "VPB", "TCB", "VHM", "VNM", "MWG", "FPT", "MSN", "SSI", "STB", "MBB", "VIC",
]


def _split(s: str) -> list[str]:
    return [t.strip().upper() for t in s.replace(" ", ",").split(",") if t.strip()]


def _parse_date(s: str) -> date:
    return datetime.strptime(s.strip(), "%Y-%m-%d").date()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m app.enrichment.cli", description=__doc__)
    p.add_argument("--database-url", default=None)
    p.add_argument("--json", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    n = sub.add_parser("news", help="ingest HSX exchange news")
    n.add_argument("--days", type=int, default=30, help="lookback window (ignored if --start given)")
    n.add_argument("--start", type=_parse_date, default=None)
    n.add_argument("--end", type=_parse_date, default=None)
    n.add_argument("--lang", action="append", choices=["vi", "en"], help="repeatable; default vi")
    n.add_argument("--max-pages", type=int, default=None)

    ca = sub.add_parser("corporate-actions", help="ingest VNDirect corporate events for symbols")
    ca.add_argument("--symbols", required=True, type=_split)

    cp = sub.add_parser("company-profiles", help="ingest VNDirect company reference for symbols")
    cp.add_argument("--symbols", required=True, type=_split)

    vh = sub.add_parser("validate-history", help="compare VNDirect EOD vs production canonical history")
    vh.add_argument("--symbols", required=True, type=_split)
    vh.add_argument("--days", type=int, default=30)
    vh.add_argument("--prod-base", default="https://backend-production-626f.up.railway.app")

    sub.add_parser("bootstrap", help="curated one-shot: news (30d) + corp actions + profiles for the demo universe")
    sub.add_parser("status", help="row counts + recent fetch log")

    return p


def _resolve_db_url(args) -> str:
    url = args.database_url or settings.DATABASE_URL
    if not url:
        print("error: no DATABASE_URL", file=sys.stderr)
        raise SystemExit(2)
    if "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://").replace("postgres://", "postgresql+asyncpg://")
    return url


async def _wire(args):
    from app.persistence import database as db

    engine = db.create_engine_from_url(_resolve_db_url(args))
    sm = db.configure(engine)
    return engine, sm


def _emit(args, payload) -> None:
    print(json.dumps(payload, indent=2, default=str))


# --------------------------------------------------------------------------- #
async def _cmd_news(args) -> int:
    from app.enrichment.http import EnrichmentHttpClient
    from app.enrichment.normalize import normalize_hsx_news
    from app.enrichment.service import EnrichmentService, UpsertResult
    from app.enrichment.sources import HsxNewsSource
    from app.persistence.models import ExternalNews

    engine, sm = await _wire(args)
    langs = args.lang or ["vi"]
    start = args.start or (date.today() - timedelta(days=max(1, args.days)))
    end = args.end or date.today()
    svc = EnrichmentService(sm)
    total = UpsertResult()
    per_lang = {}
    try:
        async with EnrichmentHttpClient(sessionmaker=sm) as client:
            src = HsxNewsSource(client)
            for lang in langs:
                acc = UpsertResult()
                pages = 0
                async for page, items, paging in src.iter_pages(
                    lang=lang, start_date=start, end_date=end, max_pages=args.max_pages
                ):
                    pages = page
                    rows = [normalize_hsx_news(it, lang=lang) for it in items]
                    r = await svc.upsert_news(rows)
                    acc.merge(r)
                per_lang[lang] = {"pages": pages, "inserted": acc.inserted, "updated": acc.updated, "skipped": acc.skipped}
                total.merge(acc)
        _emit(args, {"command": "news", "window": [start.isoformat(), end.isoformat()],
                     "per_lang": per_lang,
                     "totals": {"inserted": total.inserted, "updated": total.updated, "skipped": total.skipped},
                     "external_news_rows": await svc.count(ExternalNews)})
        return 0
    finally:
        await engine.dispose()


async def _cmd_corporate_actions(args) -> int:
    from app.enrichment.http import EnrichmentHttpClient
    from app.enrichment.normalize import normalize_vndirect_event
    from app.enrichment.service import EnrichmentService, UpsertResult
    from app.enrichment.sources import VndirectFinfoSource

    engine, sm = await _wire(args)
    svc = EnrichmentService(sm)
    total = UpsertResult()
    per_symbol = {}
    try:
        async with EnrichmentHttpClient(sessionmaker=sm) as client:
            src = VndirectFinfoSource(client)
            for sym in args.symbols:
                try:
                    raw = await src.events(sym)
                except Exception as e:  # noqa: BLE001 - one symbol failing must not abort the run
                    per_symbol[sym] = {"error": str(e)}
                    total.errors.append(f"{sym}: {e}")
                    continue
                rows = [normalize_vndirect_event(it) for it in raw]
                r = await svc.upsert_corporate_actions(rows)
                per_symbol[sym] = {"fetched": len(raw), "inserted": r.inserted, "updated": r.updated, "skipped": r.skipped}
                total.merge(r)
        _emit(args, {"command": "corporate-actions", "per_symbol": per_symbol,
                     "totals": {"inserted": total.inserted, "updated": total.updated, "skipped": total.skipped,
                                "errors": total.errors}})
        return 0 if not total.errors else 1
    finally:
        await engine.dispose()


async def _cmd_company_profiles(args) -> int:
    from app.enrichment.http import EnrichmentHttpClient
    from app.enrichment.normalize import normalize_vndirect_profile
    from app.enrichment.service import EnrichmentService, UpsertResult
    from app.enrichment.sources import VndirectFinfoSource

    engine, sm = await _wire(args)
    svc = EnrichmentService(sm)
    total = UpsertResult()
    per_symbol = {}
    try:
        async with EnrichmentHttpClient(sessionmaker=sm) as client:
            src = VndirectFinfoSource(client)
            for sym in args.symbols:
                try:
                    raw = await src.company_profile(sym)
                except Exception as e:  # noqa: BLE001
                    per_symbol[sym] = {"error": str(e)}
                    total.errors.append(f"{sym}: {e}")
                    continue
                r = await svc.upsert_company_profile(normalize_vndirect_profile(raw) if raw else None)
                per_symbol[sym] = {"found": raw is not None, "inserted": r.inserted, "updated": r.updated}
                total.merge(r)
        _emit(args, {"command": "company-profiles", "per_symbol": per_symbol,
                     "totals": {"inserted": total.inserted, "updated": total.updated, "skipped": total.skipped,
                                "errors": total.errors}})
        return 0 if not total.errors else 1
    finally:
        await engine.dispose()


async def _cmd_validate_history(args) -> int:
    import urllib.request

    from app.enrichment.http import EnrichmentHttpClient
    from app.enrichment.sources import VndirectFinfoSource

    engine, sm = await _wire(args)
    frm = date.today() - timedelta(days=max(5, args.days))
    to = date.today()
    report = {"command": "validate-history", "window": [frm.isoformat(), to.isoformat()], "symbols": {}}
    try:
        async with EnrichmentHttpClient(sessionmaker=sm) as client:
            src = VndirectFinfoSource(client)
            for sym in args.symbols:
                vd = await src.stock_prices(sym, from_date=frm, to_date=to)
                vd_by_date = {b["date"]: b for b in vd}
                # production canonical history over the public API (Postgres-first, adjusted)
                url = f"{args.prod_base}/api/market/history/{sym}?timeframe=1D&adjusted=true"
                try:
                    with urllib.request.urlopen(url, timeout=25) as resp:
                        prod = json.loads(resp.read())
                except Exception as e:  # noqa: BLE001
                    report["symbols"][sym] = {"error": f"prod fetch failed: {e}"}
                    continue
                prod_list = prod if isinstance(prod, list) else prod.get("data", [])
                prod_by_date = {b["date"]: b for b in prod_list}
                close_match = close_total = vol_close_pct = 0
                mismatches = []
                for d, b in vd_by_date.items():
                    p = prod_by_date.get(d)
                    if not p:
                        continue
                    close_total += 1
                    vd_close = round(float(b["adClose"]) * 1000)
                    p_close = round(float(p["close"]))
                    if abs(vd_close - p_close) <= 1:
                        close_match += 1
                    else:
                        mismatches.append({"date": d, "vnd": vd_close, "prod": p_close})
                    pv = p.get("volume") or 0
                    vv = int(b.get("nmVolume") or 0)
                    if pv:
                        vol_close_pct = max(vol_close_pct, abs(pv - vv) / pv * 100)
                report["symbols"][sym] = {
                    "sessions_compared": close_total,
                    "close_exact_match": close_match,
                    "close_match_rate": round(close_match / close_total, 4) if close_total else None,
                    "max_volume_delta_pct": round(vol_close_pct, 3),
                    "prod_bar_count": len(prod_list),
                    "vnd_bar_count": len(vd),
                    "mismatches": mismatches[:5],
                }
        _emit(args, report)
        return 0
    finally:
        await engine.dispose()


async def _cmd_bootstrap(args) -> int:
    common = dict(database_url=getattr(args, "database_url", None), json=True, verbose=False)
    news_args = argparse.Namespace(**common, days=30, start=None, end=None, lang=["vi", "en"], max_pages=None)
    sym_args = argparse.Namespace(**common, symbols=list(BOOTSTRAP_SYMBOLS))
    rc = 0
    rc |= await _cmd_news(news_args)
    rc |= await _cmd_corporate_actions(sym_args)
    rc |= await _cmd_company_profiles(argparse.Namespace(**common, symbols=list(BOOTSTRAP_SYMBOLS)))
    return rc


async def _cmd_status(args) -> int:
    from sqlalchemy import desc, func, select

    from app.persistence import database as db
    from app.persistence.models import (
        CompanyProfile,
        CorporateAction,
        ExternalNews,
        SourceFetchLog,
    )

    engine = db.create_engine_from_url(_resolve_db_url(args))
    sm = db.configure(engine)
    try:
        async with sm() as s:
            counts = {}
            for m in (ExternalNews, CorporateAction, CompanyProfile, SourceFetchLog):
                counts[m.__tablename__] = int((await s.execute(select(func.count()).select_from(m))).scalar() or 0)
            recent = (
                await s.execute(select(SourceFetchLog).order_by(desc(SourceFetchLog.fetched_at)).limit(10))
            ).scalars().all()
        _emit(args, {
            "command": "status",
            "counts": counts,
            "recent_fetches": [
                {"source": r.source, "endpoint": r.endpoint, "symbol": r.symbol, "status": r.http_status,
                 "items": r.item_count, "ok": r.ok, "ms": r.duration_ms, "at": r.fetched_at}
                for r in recent
            ],
        })
        return 0
    finally:
        await engine.dispose()


_HANDLERS = {
    "news": _cmd_news,
    "corporate-actions": _cmd_corporate_actions,
    "company-profiles": _cmd_company_profiles,
    "validate-history": _cmd_validate_history,
    "bootstrap": _cmd_bootstrap,
    "status": _cmd_status,
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
        print("\ninterrupted — upserts are idempotent, rerun to resume.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
