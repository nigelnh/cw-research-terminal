"""Command-line entrypoints for research-enrichment ingestion (Step 14A + 14B).

    python -m app.enrichment.cli news --days 30 --lang vi
    python -m app.enrichment.cli corporate-actions --symbols HPG,VPB,TCB
    python -m app.enrichment.cli company-profiles --symbols HPG,VPB,TCB
    python -m app.enrichment.cli backfill-events        # SSI company events, ~24mo, registry universe
    python -m app.enrichment.cli backfill-news --lang vi            # HOSE news, ~24mo, adaptive split (EN only on explicit --lang en)
    python -m app.enrichment.cli enrich-incremental     # rolling-overlap incremental crawl (HOSE vi only by default)
    python -m app.enrichment.cli coverage               # per-window completeness report
    python -m app.enrichment.cli validate-history --symbols HPG,VPB,TCB,VHM --days 30
    python -m app.enrichment.cli bootstrap              # curated universe + 30d news window
    python -m app.enrichment.cli status

Write commands (``news`` / ``corporate-actions`` / ``company-profiles`` / ``backfill-*`` /
``enrich-incremental`` / ``bootstrap``) run a ``_preflight`` DB-size check first and abort
at/above ``ENRICHMENT_DB_SIZE_CEILING_MB`` — a guard added after the 2026-08-31 volume-fill
incident. ``backfill-news`` also re-checks between monthly windows and stops cleanly (the
``source_fetch_log`` window rows make it resumable). ``validate-history`` / ``coverage`` /
``status`` are read-only. There is no scheduler.

The unattended crawls (``enrich-incremental`` / ``bootstrap``) ingest HOSE
``ENRICHMENT_INCREMENTAL_HOSE_LANGS`` (default ``vi``) — EN market-wide ingestion is
deferred post-incident. A deliberate EN pull is an explicit ``backfill-news --lang en``.
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


def _incremental_hose_langs() -> list[str]:
    """Which HOSE *source* feed(s) the unattended crawls ingest — a data-ownership
    choice, not the product's display language (the product is English-first
    regardless; see docs/design/LANGUAGE_POLICY.md).

    Defaults to ``["vi"]``: VI (langId=1) is the canonical HOSE feed with full,
    useful coverage. EN (langId=2) is a disjoint id-space dominated by ETF-NAV /
    foreign-holding notices, so EN market-wide ingestion stays off. A deliberate
    EN pull is still an explicit ``backfill-news --lang en``.
    """
    langs = [x.strip().lower() for x in settings.ENRICHMENT_INCREMENTAL_HOSE_LANGS.split(",") if x.strip()]
    return [x for x in langs if x in ("vi", "en")] or ["vi"]


def _parse_date(s: str) -> date:
    return datetime.strptime(s.strip(), "%Y-%m-%d").date()


def _vn_today() -> date:
    """Canonical Asia/Ho_Chi_Minh calendar date."""
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date()


def _months_ago(d: date, months: int) -> date:
    y, m = d.year, d.month - months
    while m <= 0:
        m += 12
        y -= 1
    # clamp day (e.g. 31 Aug - 6 months -> 28/29 Feb)
    import calendar

    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def _year_chunks(start: date, end: date) -> list[tuple[date, date]]:
    """Split [start, end] into <=1-calendar-year windows (SSI rejects longer ranges)."""
    out: list[tuple[date, date]] = []
    cur = start
    while cur <= end:
        year_end = date(cur.year, 12, 31)
        w_end = min(year_end, end)
        out.append((cur, w_end))
        cur = date(cur.year + 1, 1, 1)
    return out


async def _underlying_universe() -> list[str]:
    """CW underlying symbols from the canonical registry — not the watchlist."""
    from app.instruments.instrument_registry import instrument_registry

    try:
        await instrument_registry.initialize()
        unds = await instrument_registry.get_underlyings(active_only=False)
    except Exception as e:  # noqa: BLE001
        logger.warning("registry unavailable (%s); falling back to bootstrap set", e)
        return list(BOOTSTRAP_SYMBOLS)
    return sorted(set(unds) | set(BOOTSTRAP_SYMBOLS)) if unds else list(BOOTSTRAP_SYMBOLS)


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

    ca = sub.add_parser("corporate-actions", help="ingest VNDirect company events for symbols")
    ca.add_argument("--symbols", required=True, type=_split)

    cp = sub.add_parser("company-profiles", help="ingest VNDirect company reference for symbols")
    cp.add_argument("--symbols", required=True, type=_split)

    be = sub.add_parser("backfill-events", help="SSI structured company events — ~24mo, per underlying, year chunks")
    be.add_argument("--symbols", type=_split, default=None, help="default: CW underlying universe from the registry")
    be.add_argument("--months", type=int, default=24)
    be.add_argument("--start", type=_parse_date, default=None)
    be.add_argument("--end", type=_parse_date, default=None)

    bn = sub.add_parser("backfill-news", help="HOSE news — ~24mo, monthly windows with adaptive splitting")
    bn.add_argument("--lang", action="append", choices=["vi", "en"], help="repeatable; default vi")
    bn.add_argument("--months", type=int, default=24)
    bn.add_argument("--start", type=_parse_date, default=None)
    bn.add_argument("--end", type=_parse_date, default=None)
    bn.add_argument("--page-size", type=int, default=None)
    bn.add_argument("--max-pages", type=int, default=None)

    sub.add_parser("enrich-incremental", help="rolling-overlap incremental crawl (SSI + HOSE)")
    sub.add_parser("coverage", help="report per-window backfill completeness")

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


async def _db_size_mb(sm) -> float:
    from sqlalchemy import text

    async with sm() as s:
        b = (await s.execute(text("select pg_database_size(current_database())"))).scalar() or 0
    return round(int(b) / (1024 * 1024), 1)


async def _preflight(sm, *, allow_over: bool = False) -> float:
    """Abort a write command before it can fill a small production volume.

    The 2026-08-31 incident: a 24-month market-wide corpus of full raw JSON payloads
    exhausted the 434 MiB Railway volume and crashlooped Postgres. This guard makes
    enrichment fail loudly at a safe threshold instead.
    """
    size = await _db_size_mb(sm)
    ceiling = float(settings.ENRICHMENT_DB_SIZE_CEILING_MB)
    if size >= ceiling and not allow_over:
        print(
            f"error: database is {size} MB, at/over the {ceiling} MB enrichment ceiling.\n"
            f"       Refusing to run a write command. Raise ENRICHMENT_DB_SIZE_CEILING_MB "
            f"only after confirming real volume headroom, or reduce retention.",
            file=sys.stderr,
        )
        raise SystemExit(3)
    if size >= ceiling * 0.85:
        print(f"[preflight] WARNING: database is {size} MB (ceiling {ceiling} MB) — approaching the limit", file=sys.stderr)
    else:
        print(f"[preflight] database is {size} MB / {ceiling} MB ceiling", file=sys.stderr)
    return size


def _emit(args, payload) -> None:
    print(json.dumps(payload, indent=2, default=str))


# --------------------------------------------------------------------------- #
async def _resolve_categories(src, rows: list[dict], *, lang: str, cache: dict[tuple, str]) -> None:
    """Backfill ``category`` names for rows that only have a numeric ``cat_id``.

    HSX's list endpoint omits ``catName``; the detail endpoint has it. We fetch detail
    ONCE per distinct ``(lang, catId)`` (≈15-20 categories per language), cache the
    mapping for the whole run, and never fetch again. A failed lookup is cached as "" so
    it is not retried.
    """
    for r in rows:
        cid = r.get("cat_id")
        if not cid or r.get("category"):
            continue
        key = (lang, cid)
        if key not in cache:
            detail = None
            try:
                detail = await src.get_detail(r["source_id"], lang=lang)
            except Exception:  # noqa: BLE001 - category is cosmetic; never break ingestion
                detail = None
            name = (detail or {}).get("catName") if isinstance(detail, dict) else None
            cache[key] = str(name)[:200] if name else ""
        if cache[key]:
            r["category"] = cache[key]


async def _cmd_news(args) -> int:
    from app.enrichment.http import EnrichmentHttpClient
    from app.enrichment.normalize import normalize_hsx_news
    from app.enrichment.service import EnrichmentService, UpsertResult
    from app.enrichment.sources import HsxNewsSource
    from app.persistence.models import ExternalNews

    engine, sm = await _wire(args)
    await _preflight(sm)
    langs = args.lang or ["vi"]
    start = args.start or (date.today() - timedelta(days=max(1, args.days)))
    end = args.end or date.today()
    svc = EnrichmentService(sm)
    total = UpsertResult()
    per_lang = {}
    cat_cache: dict[tuple, str] = {}
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
                    await _resolve_categories(src, rows, lang=lang, cache=cat_cache)
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
    await _preflight(sm)
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
    await _preflight(sm)
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


async def _log_window(sm, *, source, endpoint, symbol, window, page, ok, item_count, inserted, updated, complete, error=None):
    from app.persistence.models import SourceFetchLog

    try:
        async with sm() as s:
            s.add(SourceFetchLog(
                source=source, endpoint=endpoint[:120], symbol=symbol,
                http_status=200 if ok else None, item_count=item_count, ok=ok,
                error=(error[:1000] if error else None), duration_ms=None,
                window_start=window[0], window_end=window[1], page=page,
                inserted=inserted, updated=updated, complete=complete,
            ))
            await s.commit()
    except Exception as e:  # noqa: BLE001 - observability must never break ingestion
        logger.warning("window log failed: %s", e)


# --------------------------------------------------------------------------- #
async def _cmd_backfill_events(args) -> int:
    """SSI structured company events — ~24 months, per underlying, year chunks."""
    from app.enrichment.http import EnrichmentHttpClient
    from app.enrichment.normalize import normalize_ssi_event
    from app.enrichment.service import EnrichmentService, UpsertResult
    from app.enrichment.sources import SsiCompanyEventsSource

    engine, sm = await _wire(args)
    await _preflight(sm)
    symbols = args.symbols or await _underlying_universe()
    end = args.end or _vn_today()
    start = args.start or _months_ago(end, args.months)
    svc = EnrichmentService(sm)
    total = UpsertResult()
    per_symbol: dict = {}
    try:
        async with EnrichmentHttpClient(sessionmaker=sm) as client:
            src = SsiCompanyEventsSource(client)
            for sym in symbols:
                acc = UpsertResult()
                fetched = 0
                dates: list = []
                try:
                    for w_start, w_end in _year_chunks(start, end):
                        async for page, items, paging in src.iter_events(
                            sym, from_date=w_start, to_date=w_end, language="vi"
                        ):
                            fetched += len(items)
                            rows = [normalize_ssi_event(it) for it in items]
                            dates += [r["public_date"] for r in rows if r and r.get("public_date")]
                            r = await svc.upsert_company_events(rows)
                            acc.merge(r)
                            await _log_window(
                                sm, source="SSI", endpoint="company-events", symbol=sym,
                                window=(w_start, w_end), page=page, ok=True,
                                item_count=len(items), inserted=r.inserted, updated=r.updated,
                                complete=(page >= int(paging.get("totalPage") or 1)),
                            )
                except Exception as e:  # noqa: BLE001
                    per_symbol[sym] = {"error": str(e)}
                    total.errors.append(f"{sym}: {e}")
                    continue
                per_symbol[sym] = {
                    "fetched": fetched, "inserted": acc.inserted, "updated": acc.updated,
                    "earliest": min(dates).isoformat() if dates else None,
                    "latest": max(dates).isoformat() if dates else None,
                }
                total.merge(acc)
        _emit(args, {
            "command": "backfill-events", "window": [start.isoformat(), end.isoformat()],
            "symbols": symbols, "per_symbol": per_symbol,
            "totals": {"inserted": total.inserted, "updated": total.updated,
                       "skipped": total.skipped, "errors": total.errors},
        })
        return 0 if not total.errors else 1
    finally:
        await engine.dispose()


async def _cmd_backfill_news(args) -> int:
    """HOSE news — ~24 months, market-wide, monthly windows with adaptive splitting."""
    from app.enrichment.hose_crawler import crawl_window, month_windows
    from app.enrichment.http import EnrichmentHttpClient
    from app.enrichment.normalize import normalize_hsx_news
    from app.enrichment.service import EnrichmentService, UpsertResult
    from app.enrichment.sources import HsxNewsSource

    engine, sm = await _wire(args)
    await _preflight(sm)
    langs = args.lang or ["vi"]
    end = args.end or _vn_today()
    start = args.start or _months_ago(end, args.months)
    page_size = int(args.page_size or settings.ENRICHMENT_BACKFILL_PAGE_SIZE)
    svc = EnrichmentService(sm)
    total = UpsertResult()
    per_lang: dict = {}
    incomplete: list = []
    stopped_early: str | None = None
    ceiling = float(settings.ENRICHMENT_DB_SIZE_CEILING_MB)
    try:
        async with EnrichmentHttpClient(sessionmaker=sm) as client:
            src = HsxNewsSource(client)
            cat_cache: dict = {}
            for lang in langs:
                acc = UpsertResult()
                months = 0
                splits = 0
                for w_start, w_end in month_windows(start, end):
                    # Stop cleanly before disk pressure — the log rows make the run resumable.
                    sz = await _db_size_mb(sm)
                    if sz >= ceiling:
                        stopped_early = f"{lang} at {w_start} — DB {sz} MB reached the {ceiling} MB ceiling"
                        logger.warning("backfill-news stopping early: %s", stopped_early)
                        break
                    months += 1

                    async def on_page(items, _lang=lang):
                        rows = [normalize_hsx_news(it, lang=_lang) for it in items]
                        await _resolve_categories(src, rows, lang=_lang, cache=cat_cache)
                        r = await svc.upsert_news(rows)
                        acc.merge(r)

                    wr = await crawl_window(
                        src, lang=lang, start=w_start, end=w_end, on_page=on_page,
                        page_size=page_size, max_pages=args.max_pages,
                    )
                    splits += wr.splits
                    for leaf in wr.flatten():
                        await _log_window(
                            sm, source="HOSE", endpoint="news", symbol=None,
                            window=(leaf.start, leaf.end), page=leaf.pages, ok=True,
                            item_count=leaf.items, inserted=None, updated=None,
                            complete=leaf.complete,
                        )
                        if not leaf.complete:
                            incomplete.append(f"{lang} {leaf.start}..{leaf.end}")
                per_lang[lang] = {"months": months, "adaptive_splits": splits,
                                  "inserted": acc.inserted, "updated": acc.updated}
                total.merge(acc)
                if stopped_early:
                    break
        _emit(args, {
            "command": "backfill-news", "window": [start.isoformat(), end.isoformat()],
            "per_lang": per_lang, "incomplete_windows": incomplete,
            "stopped_early": stopped_early,
            "db_size_mb": await _db_size_mb(sm),
            "totals": {"inserted": total.inserted, "updated": total.updated, "skipped": total.skipped},
        })
        return 0 if (not incomplete and not stopped_early) else 1
    finally:
        await engine.dispose()


async def _cmd_enrich_incremental(args) -> int:
    """Rolling-overlap incremental crawl for SSI + HOSE. Idempotent; safe to run often."""
    end = _vn_today()
    ssi_start = end - timedelta(days=settings.ENRICHMENT_INCREMENTAL_SSI_DAYS)
    hose_start = end - timedelta(days=settings.ENRICHMENT_INCREMENTAL_HOSE_DAYS)
    common = dict(database_url=getattr(args, "database_url", None), json=True, verbose=False)
    rc = 0
    rc |= await _cmd_backfill_events(argparse.Namespace(
        **common, symbols=None, months=2, start=ssi_start, end=end))
    rc |= await _cmd_backfill_news(argparse.Namespace(
        **common, lang=_incremental_hose_langs(), months=1, start=hose_start, end=end,
        page_size=None, max_pages=None))
    return rc


async def _cmd_coverage(args) -> int:
    from sqlalchemy import func, select

    from app.persistence import database as db
    from app.persistence.models import SourceFetchLog

    engine = db.create_engine_from_url(_resolve_db_url(args))
    sm = db.configure(engine)
    try:
        async with sm() as s:
            rows = (await s.execute(
                select(SourceFetchLog.source, SourceFetchLog.window_start, SourceFetchLog.window_end,
                       SourceFetchLog.complete, func.count().label("n"))
                .where(SourceFetchLog.window_start.isnot(None))
                .group_by(SourceFetchLog.source, SourceFetchLog.window_start,
                          SourceFetchLog.window_end, SourceFetchLog.complete)
                .order_by(SourceFetchLog.source, SourceFetchLog.window_start)
            )).all()
        incomplete = [
            {"source": r.source, "start": r.window_start.isoformat(), "end": r.window_end.isoformat()}
            for r in rows if r.complete is False
        ]
        _emit(args, {
            "command": "coverage",
            "windows_logged": len(rows),
            "incomplete": incomplete,
            "all_complete": not incomplete,
        })
        return 0 if not incomplete else 1
    finally:
        await engine.dispose()


async def _cmd_bootstrap(args) -> int:
    common = dict(database_url=getattr(args, "database_url", None), json=True, verbose=False)
    news_args = argparse.Namespace(**common, days=30, start=None, end=None, lang=_incremental_hose_langs(), max_pages=None)
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
        CompanyEvent,
        CompanyProfile,
        ExternalNews,
        SourceFetchLog,
    )

    engine = db.create_engine_from_url(_resolve_db_url(args))
    sm = db.configure(engine)
    try:
        async with sm() as s:
            counts = {}
            for m in (ExternalNews, CompanyEvent, CompanyProfile, SourceFetchLog):
                counts[m.__tablename__] = int((await s.execute(select(func.count()).select_from(m))).scalar() or 0)
            by_class = {
                r[0]: r[1] for r in (await s.execute(
                    select(CompanyEvent.event_class, func.count()).group_by(CompanyEvent.event_class)
                )).all()
            }
            by_news_source = {
                r[0]: r[1] for r in (await s.execute(
                    select(ExternalNews.source, func.count()).group_by(ExternalNews.source)
                )).all()
            }
            recent = (
                await s.execute(select(SourceFetchLog).order_by(desc(SourceFetchLog.fetched_at)).limit(10))
            ).scalars().all()
        _emit(args, {
            "command": "status",
            "counts": counts,
            "company_events_by_class": by_class,
            "news_by_source": by_news_source,
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
    "backfill-events": _cmd_backfill_events,
    "backfill-news": _cmd_backfill_news,
    "enrich-incremental": _cmd_enrich_incremental,
    "coverage": _cmd_coverage,
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
