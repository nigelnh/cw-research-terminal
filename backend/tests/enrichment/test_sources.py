"""Source clients against a mocked HTTP transport — no live network, fully deterministic.

Covers: pagination + hard cap, transient-retry, non-retryable failure isolation,
per-attempt fetch shapes. `asyncio_mode = auto` (pytest.ini) runs the coroutines.
"""

from __future__ import annotations

import httpx
import pytest

from app.enrichment.http import EnrichmentHttpClient, SourceFetchError
from app.enrichment.sources import HsxNewsSource, VndirectFinfoSource


def _mock_client(handler) -> EnrichmentHttpClient:
    c = EnrichmentHttpClient()
    c._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))  # type: ignore[attr-defined]
    return c


def _news_page(page: int, total_pages: int, n: int = 3) -> dict:
    return {
        "data": {
            "list": [
                {"id": page * 100 + i, "title": f"SYM{i}: headline {page}.{i}", "publishFrom": 1787875200}
                for i in range(n)
            ],
            "paging": {"pageIndex": page, "pageSize": n, "totalCount": total_pages * n, "totalPages": total_pages},
        },
        "success": True,
    }


async def test_news_pagination_walks_and_stops_at_total_pages():
    seen_pages: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("pageIndex", "1"))
        seen_pages.append(page)
        return httpx.Response(200, json=_news_page(page, total_pages=3))

    client = _mock_client(handler)
    src = HsxNewsSource(client)
    collected = [(page, len(items)) async for page, items, _ in src.iter_pages(lang="vi", max_pages=50)]
    await client._client.aclose()  # type: ignore[attr-defined]

    assert seen_pages == [1, 2, 3]  # stopped at totalPages, not the cap
    assert collected == [(1, 3), (2, 3), (3, 3)]


async def test_news_pagination_hard_cap():
    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("pageIndex", "1"))
        return httpx.Response(200, json=_news_page(page, total_pages=999))

    client = _mock_client(handler)
    src = HsxNewsSource(client)
    pages = [p async for p, _, _ in src.iter_pages(lang="vi", max_pages=4)]
    await client._client.aclose()  # type: ignore[attr-defined]
    assert pages == [1, 2, 3, 4]  # cap honored despite totalPages=999


async def _instant_sleep(*_args, **_kw):
    return None


async def test_transient_5xx_then_success_retries(monkeypatch):
    monkeypatch.setattr("asyncio.sleep", _instant_sleep)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, text="upstream down")
        return httpx.Response(200, json={"data": [{"code": "HPG", "id": "1.VN"}]})

    client = _mock_client(handler)
    client._max_retries = 3  # type: ignore[attr-defined]
    res = await client.get_json("https://x/v4/events", source="VNDIRECT", endpoint="events")
    await client._client.aclose()  # type: ignore[attr-defined]
    assert calls["n"] == 3
    assert res.status == 200


async def test_non_retryable_404_raises_without_retry():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(404, text="not found")

    client = _mock_client(handler)
    client._max_retries = 3  # type: ignore[attr-defined]
    with pytest.raises(SourceFetchError):
        await client.get_json("https://x/v4/missing", source="VNDIRECT", endpoint="missing")
    await client._client.aclose()  # type: ignore[attr-defined]
    assert calls["n"] == 1


async def test_vndirect_events_and_profile_shapes():
    def handler(request: httpx.Request) -> httpx.Response:
        if "events" in request.url.path:
            return httpx.Response(200, json={"data": [
                {"id": "1.VN", "code": "HPG", "type": "schedDiv", "note": "cổ tức bằng cổ phiếu", "ratio": 10.0},
            ]})
        if "company_profiles" in request.url.path:
            return httpx.Response(200, json={"data": [{"code": "HPG", "floor": "HOSE", "vnName": "Hòa Phát"}]})
        return httpx.Response(200, json={"data": []})

    client = _mock_client(handler)
    src = VndirectFinfoSource(client)
    evs = await src.events("HPG")
    prof = await src.company_profile("HPG")
    await client._client.aclose()  # type: ignore[attr-defined]
    assert evs and evs[0]["code"] == "HPG"
    assert prof and prof["vnName"] == "Hòa Phát"
