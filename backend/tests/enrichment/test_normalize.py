"""Pure normalization — no I/O. Real-shaped fixtures captured from the live sources."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from app.enrichment import normalize as N


# --------------------------------------------------------------- symbol linkage
@pytest.mark.parametrize(
    "title, expected",
    [
        ("MSH: Giải trình BCTC soát xét 6 tháng đầu năm 2026", ["MSH"]),
        ("VHM.ACBS.8M.112 Term 8 months: Results of distribution of Covered Warrants", ["VHM"]),
        ("FUEABVND: Thông báo về danh mục chứng khoán cơ cấu hoán đổi", ["FUEABVND"]),
        ("QCG: Thông báo ngày ĐKCC lấy ý kiến cổ đông", ["QCG"]),
        ("Market update with no colon prefix", []),
        ("This is a full sentence: with a colon but no ticker", []),
        ("", []),
    ],
)
def test_extract_symbols_from_title(title, expected):
    assert N.extract_symbols_from_title(title) == expected


def test_strip_html():
    assert N.strip_html("<p>Công ty  <b>Cổ phần</b></p>") == "Công ty Cổ phần"
    assert N.strip_html(None) is None
    assert N.strip_html("   ") is None
    assert N.strip_html("a &amp; b") == "a & b"


# --------------------------------------------------------------- HSX news
def test_normalize_hsx_news_epochs_and_url():
    item = {
        "id": 2493262,
        "title": "MSH: Giải trình BCTC soát xét 6 tháng đầu năm 2026",
        "summary": "<p>Công ty Cổ phần May Sông Hồng thông báo...</p>",
        "publishFrom": 1787875200,
        "approvedDate": 1787942172,
        "relatedId": 2829,
        "alias": "cong-bo-thong-tin-msh",
        "catName": "Tin Tổ chức niêm yết",
    }
    row = N.normalize_hsx_news(item, lang="vi")
    assert row["source"] == "HOSE"
    assert row["content_type"] == "exchange_disclosure"
    assert row["source_id"] == "2493262"
    assert row["lang"] == "vi"
    assert row["symbols"] == ["MSH"]
    assert row["category"] == "Tin Tổ chức niêm yết"
    assert isinstance(row["published_at"], datetime) and row["published_at"].tzinfo is timezone.utc
    assert isinstance(row["approved_at"], datetime)
    assert row["url"] and "cong-bo-thong-tin-msh" in row["url"]
    assert row["related_source_id"] == "2829"


def test_normalize_hsx_news_missing_dates():
    row = N.normalize_hsx_news({"id": 1, "title": "XYZ: y", "publishFrom": None, "postedDate": None}, lang="en")
    assert row["published_at"] is None
    assert row["symbols"] == ["XYZ"]


def test_normalize_hsx_news_cat_id_without_name():
    # list endpoint: numeric catId, no catName -> category stays None, cat_id captured
    row = N.normalize_hsx_news({"id": 5, "title": "ABC: x", "catId": 21}, lang="vi")
    assert row["category"] is None
    assert row["cat_id"] == 21
    # detail endpoint: catName present -> used directly
    row2 = N.normalize_hsx_news({"id": 5, "title": "ABC: x", "catId": 21, "catName": "Tin Tổ chức niêm yết"}, lang="vi")
    assert row2["category"] == "Tin Tổ chức niêm yết"
    assert row2["cat_id"] == 21


# --------------------------------------------------------------- VNDirect events
def test_classify_stock_dividend():
    ev = {"id": "1.VN", "code": "HPG", "type": "schedDiv", "group": "schedEvent",
          "note": "Dự kiến trả cổ tức bằng cổ phiếu năm 2025, tỷ lệ 100: 10", "ratio": 10.0, "divYear": 2025}
    r = N.normalize_vndirect_event(ev)
    assert r["event_type"] == "STOCK_DIVIDEND"
    assert r["status"] == "SCHEDULED"
    assert r["ratio_pct"] == 10.0
    assert r["ratio_text"] == "100:10"
    assert r["dividend_year"] == 2025
    assert r["cash_amount_vnd"] is None
    assert r["source_id"] == "1"  # locale suffix stripped


def test_classify_cash_dividend():
    ev = {"id": "2.VN", "code": "VNM", "type": "DIV", "group": "corpAction",
          "note": "Trả cổ tức năm 2024 bằng tiền, 1500 đ/cp", "dividend": 1500.0,
          "effectiveDate": "2026-07-10", "actualDate": "2026-07-25", "disclosureDate": "2026-06-01"}
    r = N.normalize_vndirect_event(ev)
    assert r["event_type"] == "CASH_DIVIDEND"
    assert r["status"] == "CONFIRMED"
    assert r["cash_amount_vnd"] == 1500.0
    assert r["ex_date"] == date(2026, 7, 10)
    assert r["payment_date"] == date(2026, 7, 25)
    assert r["disclosure_date"] == date(2026, 6, 1)


def test_classify_meeting_and_rights():
    agm = {"id": "3.VN", "code": "HPG", "type": "MEETING", "group": "investorRight",
           "typeDesc": "Họp ĐHCĐ", "note": "ĐHĐCĐ thường niên năm 2026", "effectiveDate": "2026-04-17"}
    assert N.normalize_vndirect_event(agm)["event_type"] == "AGM"

    rights = {"id": "4.VN", "code": "ABC", "type": "corpAction",
              "note": "Phát hành thêm cho cổ đông hiện hữu, quyền mua 2:1"}
    assert N.normalize_vndirect_event(rights)["event_type"] == "RIGHTS_ISSUE"


def test_event_missing_id_or_code_returns_none():
    assert N.normalize_vndirect_event({"code": "HPG"}) is None
    assert N.normalize_vndirect_event({"id": "9.VN"}) is None


def test_event_nan_numbers_dropped():
    r = N.normalize_vndirect_event({"id": "5.VN", "code": "HPG", "type": "schedDiv",
                                    "note": "cổ tức", "dividend": float("nan"), "ratio": float("nan")})
    assert r["cash_amount_vnd"] is None
    assert r["ratio_pct"] is None


def test_vndirect_event_carries_event_class():
    r = N.normalize_vndirect_event({"id": "7.VN", "code": "HPG", "type": "schedDiv",
                                    "note": "trả cổ tức bằng cổ phiếu", "ratio": 10.0})
    assert r["event_class"] == "DIVIDEND"


# --------------------------------------------------------------- SSI company events
def _ssi(code, title, **extra):
    return {"symbol": "HPG", "eventListCode": code, "eventName": "x", "eventTitle": title,
            "eventDescription": title, "exchange": "HOSE", "value": "0", "ratio": "0",
            "eventCode": None, **extra}


def test_ssi_classify_financial_statement():
    et, ec = N.classify_ssi_event(_ssi("KQQY", "HPG - BCTC Quý 2/2026"))
    assert (et, ec) == ("FINANCIAL_STATEMENT", "FINANCIAL")


def test_ssi_classify_insider():
    et, ec = N.classify_ssi_event(_ssi("DDRP", "HPG - Kết quả giao dịch nội bộ/CĐL"))
    assert (et, ec) == ("INSIDER_TRANSACTION", "OWNERSHIP")


def test_ssi_classify_stock_dividend_from_issuance():
    et, ec = N.classify_ssi_event(_ssi("ISS", "HPG - Phát hành cổ phiếu trả cổ tức tỷ lệ 20%"))
    assert (et, ec) == ("STOCK_DIVIDEND", "DIVIDEND")


def test_ssi_classify_agm_not_price_adjustment():
    et, ec = N.classify_ssi_event(_ssi("AGME", "HPG - Tổ chức ĐHĐCĐ thường niên 2025",
                                       exrightDate="14/03/2025", recordDate="17/03/2025"))
    assert ec == "MEETING"  # has an exright date but is NOT a price adjustment


def test_ssi_deterministic_key_stable_and_null_event_code():
    a = _ssi("KQQY", "HPG - BCTC Quý 2/2026", publicDate="30/07/2026", issueDate="30/07/2026")
    b = dict(a)  # same identifying fields
    assert N.ssi_event_key(a) == N.ssi_event_key(b)
    assert N.ssi_event_key(a).startswith("ssi_")
    c = _ssi("KQQY", "HPG - BCTC Quý 1/2026", publicDate="30/04/2026")
    assert N.ssi_event_key(a) != N.ssi_event_key(c)


def test_normalize_ssi_event_shape():
    r = N.normalize_ssi_event(_ssi(
        "ISS", "HPG - Phát hành cổ phiếu trả cổ tức năm 2024 tỷ lệ 20%",
        exrightDate="26/06/2025", recordDate="27/06/2025", publicDate="01/06/2025", ratio="0.2",
    ))
    assert r["source"] == "SSI"
    assert r["event_type"] == "STOCK_DIVIDEND"
    assert r["event_class"] == "DIVIDEND"
    assert r["ex_date"] == date(2025, 6, 26)
    assert r["public_date"] == date(2025, 6, 1)
    assert r["ratio_pct"] == 0.2
    assert r["dividend_year"] == 2024


def test_normalize_ssi_event_missing_symbol():
    assert N.normalize_ssi_event({"eventTitle": "x"}) is None


# --------------------------------------------------------------- company profile
def test_normalize_profile():
    item = {"code": "HPG", "floor": "HOSE", "vnName": "Hòa Phát",
            "enName": "Hoa Phat Group Joint Stock Company", "foundDate": "2007-01-09",
            "taxCode": "0900189284", "listedShare": 7676465850, "outstandingShare": 7676465850.0}
    r = N.normalize_vndirect_profile(item)
    assert r["symbol"] == "HPG"
    assert r["exchange"] == "HOSE"
    assert r["found_date"] == date(2007, 1, 9)
    assert r["listed_shares"] == 7676465850
    assert r["outstanding_shares"] == 7676465850
    assert r["source"] == "VNDIRECT"


def test_normalize_profile_missing_code():
    assert N.normalize_vndirect_profile({"floor": "HOSE"}) is None
