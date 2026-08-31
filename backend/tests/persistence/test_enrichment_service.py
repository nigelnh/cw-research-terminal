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

from datetime import date

import pytest

from app.ai.tools import research_tools
from app.enrichment import normalize as N
from app.enrichment import repository as repo
from app.enrichment.service import EnrichmentService
from app.persistence import database as persistence_db
from app.persistence.models import CompanyEvent, CompanyProfile, ExternalNews

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
    assert await svc.count(CompanyEvent) == 2

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


def _ssi_item(code, title, **extra):
    return {"symbol": "HPG", "eventListCode": code, "eventName": code, "eventTitle": title,
            "eventDescription": title, "exchange": "HOSE", "value": "0", "ratio": "0",
            "eventCode": None, "publicDate": "01/06/2026", **extra}


async def test_company_events_generalised_model_and_corporate_action_view(sessionmaker_):
    """SSI financials/insider are stored but excluded from the corporate-actions view."""
    svc = EnrichmentService(sessionmaker_)
    rows = [
        N.normalize_ssi_event(_ssi_item("KQQY", "HPG - BCTC Quý 2/2026", publicDate="30/07/2026")),
        N.normalize_ssi_event(_ssi_item("DDRP", "HPG - Giao dịch nội bộ", publicDate="10/07/2026")),
        N.normalize_ssi_event(_ssi_item("ISS", "HPG - trả cổ tức bằng cổ phiếu tỷ lệ 20%",
                                        exrightDate="26/06/2026", ratio="0.2")),
        N.normalize_vndirect_event(_event("900.VN", "HPG", "trả cổ tức bằng tiền",
                                          dividend=1000.0, effectiveDate="2026-05-10")),
    ]
    res = await svc.upsert_company_events(rows)
    assert res.inserted == 4

    async with sessionmaker_() as s:
        all_events = await repo.list_company_events(s, symbol="HPG", limit=50)
        ca_only = await repo.list_corporate_actions(s, symbol="HPG", limit=50)
        fin = await repo.list_company_events(s, symbol="HPG", classes=["FINANCIAL"])

    assert {e.event_class for e in all_events} == {"FINANCIAL", "OWNERSHIP", "DIVIDEND"}
    assert {e.event_class for e in ca_only} == {"DIVIDEND"}   # financials + insider excluded
    assert len(ca_only) == 2  # SSI stock dividend + VNDirect cash dividend
    assert len(fin) == 1 and fin[0].event_type == "FINANCIAL_STATEMENT"


async def test_ssi_reingest_is_idempotent_on_deterministic_key(sessionmaker_):
    svc = EnrichmentService(sessionmaker_)
    item = _ssi_item("AGME", "HPG - ĐHĐCĐ thường niên 2026", exrightDate="14/03/2026")
    r1 = await svc.upsert_company_events([N.normalize_ssi_event(item)])
    r2 = await svc.upsert_company_events([N.normalize_ssi_event(dict(item))])
    assert (r1.inserted, r2.inserted, r2.updated) == (1, 0, 1)
    assert await svc.count(CompanyEvent) == 1


async def test_unified_feed_unions_news_and_events_recent_first_no_dedup(sessionmaker_):
    svc = EnrichmentService(sessionmaker_)
    await svc.upsert_news([N.normalize_hsx_news(_news_item(1, "HPG: dividend plan", epoch=1_780_000_000), lang="vi")])
    await svc.upsert_company_events([
        N.normalize_ssi_event(_ssi_item("ISS", "HPG - trả cổ tức bằng cổ phiếu 2025",
                                        exrightDate="01/09/2026", ratio="0.1")),
    ])
    async with sessionmaker_() as s:
        rows, has_more = await repo.list_feed(s, symbol="HPG", lang="vi", limit=10)
        events_only, _ = await repo.list_feed(s, symbol="HPG", content_type="company_event", limit=10)
        news_only, _ = await repo.list_feed(s, source="HOSE", limit=10)

    assert has_more is False
    kinds = [r.content_type for r in rows]
    assert "company_event" in kinds and "exchange_disclosure" in kinds
    # both a news row AND an event row about the same dividend survive — no cross-dedup
    assert len(rows) == 2
    assert rows[0].content_type == "company_event"  # 2026 ex-date newer than the news epoch
    assert len(events_only) == 1 and events_only[0].content_type == "company_event"
    assert len(news_only) == 1 and news_only[0].source == "HOSE"


async def test_feed_default_view_hides_far_future_scheduled_events(sessionmaker_):
    """A LISTING with an effective date years out must not dominate the market-wide feed."""
    svc = EnrichmentService(sessionmaker_)
    await svc.upsert_news([N.normalize_hsx_news(_news_item(1, "HPG: recent disclosure", epoch=1_787_000_000), lang="vi")])
    await svc.upsert_company_events([
        {"source": "VNDIRECT", "source_id": "future1", "symbol": "FPT", "event_type": "LISTING",
         "event_class": "LISTING", "status": "CONFIRMED", "ex_date": date(2035, 5, 7),
         "note": "additional listing", "raw": {}},
    ])
    async with sessionmaker_() as s:
        market_wide, _ = await repo.list_feed(s, lang="vi", limit=10)   # no symbol -> horizon applies
        fpt_view, _ = await repo.list_feed(s, symbol="FPT", lang="vi", limit=10)  # per-symbol -> full

    assert [r.title for r in market_wide] == ["HPG: recent disclosure"]  # 2035 row excluded
    assert any("LISTING" in r.title for r in fpt_view)  # still reachable per-symbol


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
        it = got["items"][0]
        assert it["title"] == "HPG: hello"          # original Vietnamese preserved
        assert it["summary"] == "body"              # html stripped
        # English-first fields present
        assert it["source_language"] == "vi"
        assert it["category_en"]  # non-empty deterministic English category
        assert it["title_en"]
        assert isinstance(it["title_en_exact"], bool)


async def test_read_api_news_english_layer_renders_known_pattern(_wired_db):
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    svc = EnrichmentService(_wired_db)
    await svc.upsert_news([
        N.normalize_hsx_news(
            {"id": 77, "title": "HPG: Báo cáo tình hình quản trị công ty năm 2025",
             "publishFrom": 1_787_875_200, "catName": "Tin Tổ chức niêm yết"},
            lang="vi",
        )
    ])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        it = (await ac.get("/api/research/news", params={"symbol": "HPG"})).json()["items"][0]
    assert it["title_en"] == "Corporate governance report, 2025 — HPG"
    assert it["title_en_exact"] is True
    assert it["category_en"] == "Listed-issuer disclosure"
    assert it["title"] == "HPG: Báo cáo tình hình quản trị công ty năm 2025"  # verbatim VI kept


# ------------------------------------------------------------ incident hardening
async def test_preflight_aborts_above_db_size_ceiling(sessionmaker_, monkeypatch):
    """The write-command guard added after the 2026-08-31 volume-fill incident."""
    import pytest as _pytest

    from app.enrichment import cli
    from app.core.config import settings

    # tiny ceiling so any non-empty DB trips it
    monkeypatch.setattr(settings, "ENRICHMENT_DB_SIZE_CEILING_MB", 0)
    with _pytest.raises(SystemExit) as ei:
        await cli._preflight(sessionmaker_)
    assert ei.value.code == 3

    # generous ceiling -> returns the measured size, no raise
    monkeypatch.setattr(settings, "ENRICHMENT_DB_SIZE_CEILING_MB", 100_000)
    size = await cli._preflight(sessionmaker_)
    assert isinstance(size, float) and size > 0
