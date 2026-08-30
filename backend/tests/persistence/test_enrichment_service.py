"""Real-PostgreSQL coverage for the Step 14A enrichment layer.

Exercised end to end against the ephemeral cluster:
  * idempotent upserts (re-run -> UPDATE, never a duplicate row),
  * in-batch dedup on the natural key,
  * read repository filters / ordering,
  * the bounded read-only AI tools (causal_note + provenance always present),
  * the public read API returning a truthful empty payload vs. real rows.

No upstream source is touched — rows are built with the pure ``normalize`` functions
from captured payload shapes.
"""

from __future__ import annotations

import pytest

from app.ai.tools import research_tools
from app.enrichment import normalize as N
from app.enrichment import repository as repo
from app.enrichment.service import EnrichmentService
from app.persistence import database as persistence_db
from app.persistence.models import CompanyProfile, CorporateAction, ExternalNews

pytestmark = pytest.mark.asyncio


def _news_item(nid: int, title: str, epoch: int = 1_787_875_200) -> dict:
    return {"id": nid, "title": title, "summary": "<p>body</p>", "publishFrom": epoch,
            "alias": f"a-{nid}", "catName": "Tin Tổ chức niêm yết"}


def _event(eid: str, code: str, note: str, **extra) -> dict:
    return {"id": eid, "code": code, "type": "schedDiv", "group": "schedEvent", "note": note, **extra}


# --------------------------------------------------------------------- upserts
async def test_upsert_news_is_idempotent(sessionmaker_):
    svc = EnrichmentService(sessionmaker_)
    rows = [N.normalize_hsx_news(_news_item(1, "HPG: disclosure"), lang="vi"),
            N.normalize_hsx_news(_news_item(2, "VPB: disclosure"), lang="vi")]

    r1 = await svc.upsert_news(rows)
    assert (r1.inserted, r1.updated) == (2, 0)

    r2 = await svc.upsert_news(rows)
    assert (r2.inserted, r2.updated) == (0, 2)
    assert await svc.count(ExternalNews) == 2


async def test_upsert_corporate_actions_dedupes_within_batch(sessionmaker_):
    svc = EnrichmentService(sessionmaker_)
    dup_a = N.normalize_vndirect_event(_event("55.VN", "HPG", "cổ tức bằng cổ phiếu", ratio=10.0))
    dup_b = N.normalize_vndirect_event(_event("55.EN_GB", "HPG", "cổ tức bằng cổ phiếu tỷ lệ 100:12", ratio=12.0))
    other = N.normalize_vndirect_event(_event("56.VN", "VNM", "trả cổ tức bằng tiền", dividend=1500.0))

    res = await svc.upsert_corporate_actions([dup_a, dup_b, other, None])
    # 55.VN and 55.EN_GB collapse to source_id "55"; None is dropped.
    assert res.inserted == 2
    assert await svc.count(CorporateAction) == 2

    # last write in the batch wins for the deduped key
    async with sessionmaker_() as s:
        got = await repo.list_corporate_actions(s, symbol="HPG")
    assert got[0].ratio_pct == 12.0


async def test_upsert_company_profile_idempotent(sessionmaker_):
    svc = EnrichmentService(sessionmaker_)
    row = N.normalize_vndirect_profile(
        {"code": "HPG", "floor": "HOSE", "vnName": "Hòa Phát", "listedShare": 7676465850}
    )
    assert (await svc.upsert_company_profile(row)).inserted == 1
    assert (await svc.upsert_company_profile(row)).updated == 1
    assert await svc.count(CompanyProfile) == 1


# ----------------------------------------------------------------- repository
async def test_list_news_symbol_filter_and_facets(sessionmaker_):
    svc = EnrichmentService(sessionmaker_)
    await svc.upsert_news([
        N.normalize_hsx_news(_news_item(1, "HPG: a", epoch=1_787_000_000), lang="vi"),
        N.normalize_hsx_news(_news_item(2, "HPG: b", epoch=1_787_500_000), lang="vi"),
        N.normalize_hsx_news(_news_item(3, "VPB: c", epoch=1_787_200_000), lang="vi"),
    ])
    async with sessionmaker_() as s:
        hpg = await repo.list_news(s, symbol="hpg", lang="vi", limit=10)
        facets = await repo.news_symbol_facets(s, lang="vi")
        cnt = await repo.news_count_for_symbol(s, "HPG")

    assert [n.title for n in hpg] == ["HPG: b", "HPG: a"]  # newest first
    assert facets[0] == "HPG"  # most frequent symbol leads
    assert cnt == 2


async def test_corporate_actions_ordering_prefers_ex_date(sessionmaker_):
    svc = EnrichmentService(sessionmaker_)
    await svc.upsert_corporate_actions([
        N.normalize_vndirect_event(_event("1.VN", "HPG", "tiền", dividend=100.0, effectiveDate="2026-03-01")),
        N.normalize_vndirect_event(_event("2.VN", "HPG", "tiền", dividend=100.0, effectiveDate="2026-09-01")),
    ])
    async with sessionmaker_() as s:
        rows = await repo.list_corporate_actions(s, symbol="HPG")
    assert [r.source_id for r in rows] == ["2", "1"]


# ------------------------------------------------------------------ AI tools
@pytest.fixture
def _wired_db(sessionmaker_, monkeypatch):
    monkeypatch.setattr(persistence_db, "is_configured", lambda: True)
    monkeypatch.setattr(persistence_db, "get_sessionmaker", lambda: sessionmaker_)
    return sessionmaker_


async def test_ai_get_news_is_bounded_and_carries_causal_note(_wired_db):
    svc = EnrichmentService(_wired_db)
    await svc.upsert_news(
        [N.normalize_hsx_news(_news_item(i, f"HPG: item {i}", epoch=1_787_000_000 + i), lang="vi")
         for i in range(50)]
    )
    out = await research_tools.get_news(symbol="hpg", limit=999)
    assert out["provenance"] == "RESEARCH_ENRICHMENT"
    assert "caused" in out["causal_note"]
    assert out["count"] <= 12  # AI_NEWS_MAX_RESULTS clamp, even with limit=999


async def test_ai_get_corporate_actions_requires_symbol_and_is_unavailable_without_db():
    bad = await research_tools.get_corporate_actions("")
    assert bad["status"] == "INVALID_ARGUMENT"

    # persistence_db not monkeypatched here -> not configured in the test env
    assert not persistence_db.is_configured()
    out = await research_tools.get_corporate_actions("HPG")
    assert out["status"] == "UNAVAILABLE"


# ------------------------------------------------------------------ read API
async def test_read_api_empty_then_populated(_wired_db):
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        empty = (await ac.get("/api/research/news")).json()
        assert empty == {"items": [], "count": 0, "has_more": False, "next_before": None}

        svc = EnrichmentService(_wired_db)
        await svc.upsert_news([N.normalize_hsx_news(_news_item(9, "HPG: hello"), lang="vi")])

        got = (await ac.get("/api/research/news", params={"symbol": "HPG"})).json()
        assert got["count"] == 1
        assert got["items"][0]["title"] == "HPG: hello"
        assert got["items"][0]["summary"] == "body"  # html stripped
