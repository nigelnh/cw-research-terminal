"""Symbol event lists order by disclosure, and notes get an English face.

The instrument panel ordered on `ex_date`. For a LISTING event VNDirect puts the ESOP
VESTING date there, so FPT's panel opened on rows dated 2027-2036 while the additional
listing disclosed on 2026-08-26 - the newest thing on the record - sat below seven of them.
A row with a NULL `ex_date` fell to the bottom however recently it had been disclosed.

The DESC column was separately empty for every row: it rendered only `cash_amount_vnd` or
`ratio_text`, and 0 of 12 FPT events carried either. The substance was in `note`, withheld
because it is Vietnamese.
"""
from datetime import date

import pytest

from app.enrichment import repository as repo
from app.enrichment.english import note_en
from app.enrichment.service import EnrichmentService

pytestmark = pytest.mark.asyncio


async def _seed_mixed(sm):
    await EnrichmentService(sm).upsert_company_events([
        # An ESOP vesting schedule, disclosed years ago. `ex_date` is a decade out.
        {"source": "VNDIRECT", "source_id": "vest-2036", "symbol": "ZZZ",
         "event_type": "ADDITIONAL_LISTING", "event_class": "LISTING", "status": "CONFIRMED",
         "ex_date": date(2036, 6, 24), "public_date": date(2023, 5, 31),
         "disclosure_date": date(2023, 5, 31), "note": "Số lượng 2,302,000 CP", "raw": {}},
        # The most recent thing that actually happened. No ex_date at all - which is how
        # it fell to the BOTTOM of the old ordering, under a decade of vesting rows.
        {"source": "VNDIRECT", "source_id": "listing-2026", "symbol": "ZZZ",
         "event_type": "ADDITIONAL_LISTING", "event_class": "LISTING", "status": "CONFIRMED",
         "public_date": date(2026, 8, 26), "disclosure_date": date(2026, 8, 26),
         "note": "Số lượng 8,517,301 CP", "raw": {}},
    ])


async def test_the_panel_leads_with_what_was_disclosed_most_recently(sessionmaker_):
    await _seed_mixed(sessionmaker_)
    async with sessionmaker_() as s:
        rows = await repo.list_corporate_actions(s, symbol="ZZZ", limit=10)
    assert [r.source_id for r in rows] == ["listing-2026", "vest-2036"], (
        "a 2036 vesting date must not outrank a statement filed this year"
    )


async def test_the_other_symbol_list_orders_the_same_way(sessionmaker_):
    """Both symbol-scoped readers had the defect; fixing one would have left the other."""
    await _seed_mixed(sessionmaker_)
    async with sessionmaker_() as s:
        rows = await repo.list_company_events(s, symbol="ZZZ", limit=10)
    assert [r.source_id for r in rows] == ["listing-2026", "vest-2036"]


async def test_the_feed_still_files_an_event_under_its_ex_date(sessionmaker_):
    """`_event_sort_col` decides which calendar DAY a feed row belongs to. Recency ordering
    is a separate column precisely so this does not move."""
    await EnrichmentService(sessionmaker_).upsert_company_events([
        {"source": "SSI", "source_id": "div", "symbol": "YYY", "event_type": "CASH_DIVIDEND",
         "event_class": "DIVIDEND", "status": "CONFIRMED", "public_date": date(2026, 9, 1),
         "ex_date": date(2026, 9, 10), "note": "cổ tức", "raw": {}},
    ])
    async with sessionmaker_() as s:
        rows, _ = await repo.list_feed(
            s, symbol="YYY", date_from=date(2026, 9, 10), date_to=date(2026, 9, 10)
        )
    assert len(rows) == 1, "the ex_date is still the day this event is filed under"


# --------------------------------------------------------------------------- #
# note_en - pure, no DB
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("raw,expected", [
    ("FPT - BCTC Quý 2/2026", "FPT — Consolidated financial statements, Q2/2026"),
    ("HPG - BCTC Riêng lẻ kiểm toán Quý 4/2025",
     "HPG — Audited separate financial statements, Q4/2025"),
    ("Số lượng 2,302,000 CP", "2,302,000 shares"),
    ("Trả cổ tức năm 2025, tỷ lệ 100:10", "Dividend 2025, rate 100:10"),
    # Already English at the source - handed back, not reworded.
    ("Number of shares 3,315,000 shares", "Number of shares 3,315,000 shares"),
    ("Dividend payment 2025 (500 VND/share)", "Dividend payment 2025 (500 VND/share)"),
])
def test_note_en_renders_the_templated_shapes(raw, expected):
    assert note_en(raw) == expected


def test_an_out_of_pattern_note_declines_rather_than_inventing_a_translation():
    """The module's rule, applied here too: classify what is templated, decline the rest.
    A machine gloss of an issuer's sentence is worse than a dash on a trading screen."""
    prose = ("<p>Tập đoàn Vingroup - Công ty CP (VIC) phát hành cổ phiếu thưởng:"
             "<br /> Ngày giao dịch không hưởng quyền</p>")
    assert note_en(prose) is None


def test_markup_never_survives_into_the_rendered_note():
    """Some notes arrive as HTML fragments. Whatever is returned is text, never markup."""
    rendered = note_en("<p>Số lượng 1,820,000 CP</p>")
    assert rendered == "1,820,000 shares"
    for empty in (None, "", "   ", "<br />"):
        assert note_en(empty) is None
