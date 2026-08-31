"""HOSE adaptive-split crawler + 24-month window math. No live network."""

from __future__ import annotations

from datetime import date

import httpx

import argparse

from app.core.config import settings
from app.enrichment import cli as enrich_cli
from app.enrichment.cli import _incremental_hose_langs, _months_ago, _year_chunks
from app.enrichment.hose_crawler import crawl_window, month_windows
from app.enrichment.http import EnrichmentHttpClient
from app.enrichment.sources import HsxNewsSource


# ---------------------------------------------------------------- window math
def test_24_month_window_is_partial_year_full_year_ytd():
    end = date(2026, 8, 31)
    start = _months_ago(end, 24)
    assert start == date(2024, 8, 31)  # a real 24-month lookback, not "2025 onward"
    chunks = _year_chunks(start, end)
    assert chunks == [
        (date(2024, 8, 31), date(2024, 12, 31)),  # partial first year
        (date(2025, 1, 1), date(2025, 12, 31)),   # full intermediate year
        (date(2026, 1, 1), date(2026, 8, 31)),    # current partial year
    ]


def test_months_ago_clamps_day():
    assert _months_ago(date(2026, 8, 31), 6) == date(2026, 2, 28)


# -------------------------------------------------- incremental HOSE language policy
def test_incremental_hose_langs_defaults_to_vi_only(monkeypatch):
    monkeypatch.setattr(settings, "ENRICHMENT_INCREMENTAL_HOSE_LANGS", "vi")
    assert _incremental_hose_langs() == ["vi"]
    # garbage / empty falls back to vi, never silently to en
    monkeypatch.setattr(settings, "ENRICHMENT_INCREMENTAL_HOSE_LANGS", "  , xx ")
    assert _incremental_hose_langs() == ["vi"]
    # EN market-wide is only ingested when explicitly configured
    monkeypatch.setattr(settings, "ENRICHMENT_INCREMENTAL_HOSE_LANGS", "vi,en")
    assert _incremental_hose_langs() == ["vi", "en"]


async def test_enrich_incremental_crawls_hose_vi_only_by_default(monkeypatch):
    monkeypatch.setattr(settings, "ENRICHMENT_INCREMENTAL_HOSE_LANGS", "vi")
    seen: dict = {}

    async def _fake_events(ns):
        return 0

    async def _fake_news(ns):
        seen["lang"] = ns.lang
        return 0

    monkeypatch.setattr(enrich_cli, "_cmd_backfill_events", _fake_events)
    monkeypatch.setattr(enrich_cli, "_cmd_backfill_news", _fake_news)

    rc = await enrich_cli._cmd_enrich_incremental(
        argparse.Namespace(database_url=None, json=True, verbose=False)
    )
    assert rc == 0
    assert seen["lang"] == ["vi"]  # never re-crawls the deferred EN market-wide corpus


def test_month_windows_cover_span_contiguously():
    mw = month_windows(date(2024, 8, 15), date(2025, 1, 10))
    assert mw[0] == (date(2024, 8, 15), date(2024, 8, 31))
    assert mw[1] == (date(2024, 9, 1), date(2024, 9, 30))
    assert mw[-1] == (date(2025, 1, 1), date(2025, 1, 10))


# ---------------------------------------------------------------- adaptive split
def _paged_transport(total_by_window: dict, page_size: int = 50):
    """Mock HSX: `total_by_window` maps (start,end) iso -> total item count."""

    def handler(request: httpx.Request) -> httpx.Response:
        p = request.url.params
        key = (p.get("startDate"), p.get("endDate"))
        total = total_by_window.get(key, 0)
        idx = int(p.get("pageIndex", "1"))
        size = int(p.get("pageSize", str(page_size)))
        total_pages = max(1, (total + size - 1) // size)
        start = (idx - 1) * size
        n = max(0, min(size, total - start))
        items = [{"id": start + i, "title": f"SYM: item {start+i}", "publishFrom": 1_787_000_000}
                 for i in range(n)]
        return httpx.Response(200, json={"data": {"list": items, "paging": {
            "pageIndex": idx, "pageSize": size, "totalCount": total, "totalPages": total_pages}}})

    return httpx.MockTransport(handler)


async def test_crawl_window_splits_when_over_cap_and_reports_complete():
    # August 2026 has 150 items -> 3 pages > cap(2); split at the midpoint (Aug 16),
    # each half is <= 2 pages and fully retrievable.
    aug = ("2026-08-01", "2026-08-31")
    left = ("2026-08-01", "2026-08-16")
    right = ("2026-08-17", "2026-08-31")
    totals = {aug: 150, left: 70, right: 80}

    client = EnrichmentHttpClient()
    client._client = httpx.AsyncClient(transport=_paged_transport(totals))  # type: ignore[attr-defined]
    src = HsxNewsSource(client)

    seen: list[int] = []

    async def on_page(items):
        seen.extend(i["id"] for i in items)

    wr = await crawl_window(
        src, lang="vi", start=date(2026, 8, 1), end=date(2026, 8, 31),
        on_page=on_page, page_size=50, max_pages=2,  # cap*size = 100 < 150 -> must split
    )
    await client._client.aclose()  # type: ignore[attr-defined]

    assert wr.splits == 1
    assert wr.complete is True
    assert wr.items == 150           # every item retrieved despite the cap
    assert len(seen) == 150


async def test_crawl_window_marks_incomplete_when_cannot_split_further():
    day = ("2026-08-15", "2026-08-15")
    totals = {day: 500}  # one calendar day, 10 pages, cap 2 -> cannot split, truncates

    client = EnrichmentHttpClient()
    client._client = httpx.AsyncClient(transport=_paged_transport(totals))  # type: ignore[attr-defined]
    src = HsxNewsSource(client)

    async def on_page(items):
        return None

    wr = await crawl_window(
        src, lang="vi", start=date(2026, 8, 15), end=date(2026, 8, 15),
        on_page=on_page, page_size=50, max_pages=2,
    )
    await client._client.aclose()  # type: ignore[attr-defined]
    assert wr.complete is False       # honest: coverage of this window is incomplete
