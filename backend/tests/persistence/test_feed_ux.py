"""DB-first search/date filtering and stable cursors; no upstream provider reads."""
from datetime import date, datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.enrichment import normalize as N, repository as repo
from app.enrichment.service import EnrichmentService
from app.persistence import database

pytestmark = pytest.mark.asyncio


async def seed(sm):
    svc = EnrichmentService(sm)
    # All 45 newer rows share a timestamp; the dividend is beyond the default first page.
    await svc.upsert_news([
        N.normalize_hsx_news({"id": i, "title": f"HPG: Báo cáo tài chính {i}",
                              "publishFrom": 1788278400, "catName": "Tin Tổ chức niêm yết"}, lang="vi")
        for i in range(1, 46)
    ] + [N.normalize_hsx_news({"id": 100, "title": "VPB: Trả cổ tức bằng tiền",
                               "publishFrom": 1788105600, "catName": "Tin Tổ chức niêm yết"}, lang="vi")])
    await svc.upsert_company_events([
        {"source": "SSI", "source_id": "future", "symbol": "FPT", "event_type": "CASH_DIVIDEND",
         "event_class": "DIVIDEND", "status": "CONFIRMED", "public_date": date(2026,9,1),
         "ex_date": date(2026,9,10), "note": "cổ tức", "raw": {}},
        {"source": "SSI", "source_id": "undated", "symbol": "TCB", "event_type": "AGM",
         "event_class": "MEETING", "status": "CONFIRMED", "note": "meeting", "raw": {}},
    ])


async def test_english_literal_search_and_multi_symbols_before_pagination(sessionmaker_):
    await seed(sessionmaker_)
    async with sessionmaker_() as s:
        rows, more = await repo.list_feed(s, query="dividend", limit=40)
        assert {r.symbol for r in rows} == {"VPB", "FPT"}
        assert not more
        original, _ = await repo.list_feed(s, query="Trả cổ tức", symbols=["VPB", "FPT"])
        assert [r.symbol for r in original] == ["VPB"]
        rows, _ = await repo.list_feed(s, symbols=["VPB", "FPT"], limit=40)
        assert {r.symbol for r in rows} == {"VPB", "FPT"}
        empty, _ = await repo.list_feed(s, symbols=[])
        assert not empty
        wildcard, _ = await repo.list_feed(s, query="%")
        assert not wildcard
        assert await repo.feed_symbol_facets(s) == ["FPT", "HPG", "TCB", "VPB"]


async def test_cursor_never_loses_equal_timestamp_rows(sessionmaker_):
    await seed(sessionmaker_)
    async with sessionmaker_() as s:
        cursor, seen = None, []
        for _ in range(10):
            rows, more = await repo.list_feed(s, symbols=["HPG"], limit=7, cursor=cursor)
            seen.extend(r.id for r in rows)
            if not more:
                break
            cursor = repo.encode_feed_cursor(rows[-1])
        assert len(seen) == len(set(seen)) == 45


async def test_inclusive_ict_dates_and_source_kind(sessionmaker_):
    await seed(sessionmaker_)
    async with sessionmaker_() as s:
        # Scope this date-boundary assertion to its dated fixture. The separate undated TCB
        # event legitimately uses its observation day; letting wall-clock 2026-09-10 decide
        # whether it appears made this test fail only when the suite ran on that date.
        rows, _ = await repo.list_feed(
            s, symbol="FPT", date_from=date(2026,9,10), date_to=date(2026,9,10)
        )
        assert len(rows) == 1
        assert rows[0].symbol == "FPT"
        assert rows[0].date_kind == "ex_date"
        assert rows[0].published_at == "2026-09-10"  # backwards-compatible legacy field
        assert datetime.fromisoformat(rows[0].display_date).date() == date(2026,9,9)  # 17:00 UTC = ICT midnight
        empty, _ = await repo.list_feed(
            s, symbol="FPT", date_from=date(2026,9,11), date_to=date(2026,9,12)
        )
        assert not empty


async def test_api_additive_cursor_facets_validation(sessionmaker_, monkeypatch):
    from app.main import app
    monkeypatch.setattr(database, "is_configured", lambda: True)
    monkeypatch.setattr(database, "get_sessionmaker", lambda: sessionmaker_)
    await seed(sessionmaker_)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/research/feed", params={"symbols":"HPG", "limit":7})
        assert r.status_code == 200
        payload = r.json()
        assert payload["next_cursor"] and payload["next_before"] and payload["has_more"]
        next_page = (await c.get("/api/research/feed", params={"symbols":"HPG", "limit":7, "cursor":payload["next_cursor"]})).json()
        assert not ({r["id"] for r in payload["items"]} & {r["id"] for r in next_page["items"]})
        filtered = (await c.get("/api/research/feed", params={"q":"dividend", "symbols":"VPB,FPT"})).json()
        assert filtered["count"] == 2
        assert (await c.get("/api/research/feed", params={"symbols":""})).json()["count"] == 0
        assert (await c.get("/api/research/feed/facets")).json()["symbols"] == ["FPT", "HPG", "TCB", "VPB"]
        for params in ({"cursor":"garbage"}, {"date_from":"2026-09-10","date_to":"2026-09-01"}, {"symbols":"HPG,%"}):
            assert (await c.get("/api/research/feed", params=params)).status_code == 422


async def test_cursor_rejects_wrong_shapes():
    import base64, json
    for value in ({"a":1}, [None, "news_1"], ["invalid", "news_1"], [datetime.now(timezone.utc).isoformat(), "arbitrary"]):
        with pytest.raises(ValueError):
            repo.decode_feed_cursor(base64.urlsafe_b64encode(json.dumps(value).encode()).decode())
