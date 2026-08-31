"""Source clients: HSX news + VNDirect finfo. Fetch + page, hand raw dicts to normalize.

All calls go through EnrichmentHttpClient (bounded timeout/retry, fetch-log). Pagination
is hard-capped. These are only invoked from CLI ingestion entrypoints.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from app.core.config import settings
from app.enrichment.http import EnrichmentHttpClient

logger = logging.getLogger("app.enrichment.sources")


class HsxNewsSource:
    """HSX public disclosure feed. ``/{langId}/news`` list, langId 1=vi 2=en."""

    LANGS = {"vi": 1, "en": 2}

    def __init__(self, client: EnrichmentHttpClient) -> None:
        self._c = client
        self._base = settings.HSX_NEWS_BASE_URL.rstrip("/")

    async def iter_pages(
        self,
        *,
        lang: str = "vi",
        start_date: date | None = None,
        end_date: date | None = None,
        page_size: int | None = None,
        max_pages: int | None = None,
    ):
        lang_id = self.LANGS.get(lang, 1)
        size = int(page_size or settings.ENRICHMENT_NEWS_PAGE_SIZE)
        cap = int(max_pages or settings.ENRICHMENT_NEWS_MAX_PAGES)
        page = 1
        total_pages = None
        while page <= cap:
            params: dict[str, Any] = {"pageIndex": page, "pageSize": size}
            if start_date:
                params["startDate"] = start_date.isoformat()
            if end_date:
                params["endDate"] = end_date.isoformat()
            res = await self._c.get_json(
                f"{self._base}/{lang_id}/news",
                source="HSX",
                endpoint="news",
                params=params,
                item_count_fn=lambda d: len(_hsx_list(d)),
            )
            items = _hsx_list(res.json)
            paging = (res.json or {}).get("data", {}).get("paging") or {}
            total_pages = paging.get("totalPages")
            yield page, items, paging
            if not items:
                break
            if total_pages is not None and page >= int(total_pages):
                break
            page += 1

    async def get_detail(self, news_id: str, *, lang: str = "vi") -> dict | None:
        lang_id = self.LANGS.get(lang, 1)
        try:
            res = await self._c.get_json(
                f"{self._base}/{lang_id}/news/{news_id}",
                source="HSX",
                endpoint="news_detail",
            )
        except Exception as e:  # noqa: BLE001
            logger.info("hsx detail %s failed: %s", news_id, e)
            return None
        d = (res.json or {}).get("data")
        return d if isinstance(d, dict) else None


def _hsx_list(payload: Any) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if isinstance(data, dict):
        lst = data.get("list")
        return lst if isinstance(lst, list) else []
    return data if isinstance(data, list) else []


class VndirectFinfoSource:
    """VNDirect finfo v4: events, company_profiles, stock_prices."""

    def __init__(self, client: EnrichmentHttpClient) -> None:
        self._c = client
        self._base = settings.VNDIRECT_FINFO_BASE_URL.rstrip("/")

    async def events(self, symbol: str, *, size: int = 100) -> list[dict]:
        res = await self._c.get_json(
            f"{self._base}/events",
            source="VNDIRECT",
            endpoint="events",
            symbol=symbol,
            params={"q": f"code:{symbol.upper()}", "size": size, "sort": "disclosureDate:desc"},
            item_count_fn=lambda d: len(_vnd_data(d)),
        )
        return _vnd_data(res.json)

    async def company_profile(self, symbol: str) -> dict | None:
        res = await self._c.get_json(
            f"{self._base}/company_profiles",
            source="VNDIRECT",
            endpoint="company_profiles",
            symbol=symbol,
            params={"q": f"code:{symbol.upper()}"},
            item_count_fn=lambda d: len(_vnd_data(d)),
        )
        rows = _vnd_data(res.json)
        return rows[0] if rows else None

    async def stock_prices(
        self, symbol: str, *, from_date: date, to_date: date, size: int = 60
    ) -> list[dict]:
        q = f"code:{symbol.upper()}~date:gte:{from_date.isoformat()}~date:lte:{to_date.isoformat()}"
        res = await self._c.get_json(
            f"{self._base}/stock_prices",
            source="VNDIRECT",
            endpoint="stock_prices",
            symbol=symbol,
            params={"q": q, "size": size, "sort": "date:desc"},
            item_count_fn=lambda d: len(_vnd_data(d)),
        )
        return _vnd_data(res.json)


def _vnd_data(payload: Any) -> list[dict]:
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        return payload["data"]
    return []


class SsiCompanyEventsSource:
    """SSI structured company events: ``statistics/company/ssmi/corporate-actions``.

    The endpoint silently returns an empty payload for date ranges longer than ~1 year, so
    the caller MUST pass windows of <= 1 calendar year. Pagination is real but small
    (a single symbol rarely exceeds one page at pageSize=1000).
    """

    def __init__(self, client: EnrichmentHttpClient) -> None:
        self._c = client
        self._base = settings.SSI_IBOARD_API_BASE_URL.rstrip("/")

    async def iter_events(
        self,
        symbol: str,
        *,
        from_date: date,
        to_date: date,
        language: str = "vi",
        page_size: int = 1000,
        max_pages: int = 10,
    ):
        """Yields ``(page, items, paging)`` for one symbol over one <=1y window."""
        url = f"{self._base}/statistics/company/ssmi/corporate-actions"
        page = 1
        while page <= max_pages:
            res = await self._c.get_json(
                url,
                source="SSI",
                endpoint="company-events",
                symbol=symbol,
                params={
                    "pageSize": page_size,
                    "page": page,
                    "language": language,
                    "symbol": symbol.upper(),
                    "fromDate": from_date.strftime("%d/%m/%Y"),
                    "toDate": to_date.strftime("%d/%m/%Y"),
                },
                item_count_fn=lambda d: len(_ssi_data(d)),
            )
            items = _ssi_data(res.json)
            paging = (res.json or {}).get("paging") or {}
            yield page, items, paging
            total = paging.get("totalPage") or 0
            if not items or page >= int(total or 0):
                break
            page += 1


def _ssi_data(payload: Any) -> list[dict]:
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        return payload["data"]
    return []
