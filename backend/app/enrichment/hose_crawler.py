"""HOSE news historical crawler with adaptive date-window splitting.

HOSE is market-wide (~2,500-3,500 disclosures/month), so it is crawled by date window,
never per-ticker. A window whose page count would exceed the safety cap is split
(month -> half -> week -> …) until every sub-window is exhaustively retrievable. Each
window reports whether it completed, so `coverage` can prove there was no silent
truncation.

No FiinQuant imports. Only invoked from the CLI.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.core.config import settings
from app.enrichment.sources import HsxNewsSource

logger = logging.getLogger("app.enrichment.hose_crawler")


@dataclass(slots=True)
class WindowResult:
    start: date
    end: date
    pages: int = 0
    items: int = 0
    total_count: int = 0
    complete: bool = True
    splits: int = 0
    sub: list["WindowResult"] = field(default_factory=list)

    def flatten(self) -> list["WindowResult"]:
        if not self.sub:
            return [self]
        out: list[WindowResult] = []
        for w in self.sub:
            out.extend(w.flatten())
        return out


def _midpoint(start: date, end: date) -> date:
    return start + timedelta(days=(end - start).days // 2)


async def crawl_window(
    src: HsxNewsSource,
    *,
    lang: str,
    start: date,
    end: date,
    on_page,
    page_size: int = 200,
    max_pages: int | None = None,
    min_span_days: int = 1,
    _depth: int = 0,
) -> WindowResult:
    """Crawl [start, end] for one language, calling ``on_page(items)`` per page.

    If the window reports more pages than ``max_pages``, it is halved and each half is
    crawled recursively — so historical coverage is never dropped.
    """
    cap = int(max_pages or settings.ENRICHMENT_NEWS_MAX_PAGES)
    res = WindowResult(start=start, end=end)

    first_page_total = None
    async for page, items, paging in src.iter_pages(
        lang=lang, start_date=start, end_date=end, page_size=page_size, max_pages=cap
    ):
        if first_page_total is None:
            first_page_total = int(paging.get("totalPages") or 0)
            res.total_count = int(paging.get("totalCount") or 0)
            if first_page_total > cap and (end - start).days > min_span_days:
                # Too big for one bounded walk — split and recurse instead.
                mid = _midpoint(start, end)
                left = await crawl_window(
                    src, lang=lang, start=start, end=mid, on_page=on_page,
                    page_size=page_size, max_pages=cap, min_span_days=min_span_days,
                    _depth=_depth + 1,
                )
                right = await crawl_window(
                    src, lang=lang, start=mid + timedelta(days=1), end=end, on_page=on_page,
                    page_size=page_size, max_pages=cap, min_span_days=min_span_days,
                    _depth=_depth + 1,
                )
                res.sub = [left, right]
                res.splits = 1 + left.splits + right.splits
                res.pages = left.pages + right.pages
                res.items = left.items + right.items
                res.complete = left.complete and right.complete
                return res
        res.pages = page
        res.items += len(items)
        await on_page(items)

    # completeness: we retrieved every page the source reported for this window
    if first_page_total is not None:
        res.complete = res.pages >= first_page_total or first_page_total <= cap and res.pages >= first_page_total
        if first_page_total > cap:
            res.complete = False  # couldn't split further (span floor) and still capped
    return res


def month_windows(start: date, end: date) -> list[tuple[date, date]]:
    """Calendar-month windows covering [start, end] inclusive."""
    out: list[tuple[date, date]] = []
    cur = date(start.year, start.month, 1)
    if cur < start:
        cur = start
    while cur <= end:
        if cur.month == 12:
            nxt = date(cur.year + 1, 1, 1)
        else:
            nxt = date(cur.year, cur.month + 1, 1)
        w_end = min(nxt - timedelta(days=1), end)
        out.append((cur, w_end))
        cur = nxt
    return out
