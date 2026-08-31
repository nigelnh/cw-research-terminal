"""Deterministic English presentation layer — pure, no I/O."""

from __future__ import annotations

import pytest

from app.enrichment import english as E


# --------------------------------------------------------------------- category
@pytest.mark.parametrize(
    "vi, en",
    [
        ("Tin Tổ chức niêm yết", "Listed-issuer disclosure"),
        ("Tin quản lý thị trường", "Market administration notice"),
        ("Tin tức CW", "Covered-warrant news"),
        ("Tin về hoạt động của Sở", "Exchange operations notice"),
    ],
)
def test_category_en_known(vi, en):
    assert E.category_en(vi) == en


def test_category_en_unmapped_and_empty_degrade_safely():
    assert E.category_en("Một loại tin hoàn toàn mới") == "HOSE disclosure"
    assert E.category_en(None) == "HOSE disclosure"
    assert E.category_en("") == "HOSE disclosure"


# Vietnamese-specific letters (đ + the toned vowels). The em-dash separator "—" is
# intentional and allowed; these are not.
_VN_CHARS = set("đĐàáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵ")


def _no_vietnamese(s: str) -> bool:
    return not (_VN_CHARS & set(s.lower()))


def test_every_mapped_category_has_ascii_english():
    for vi, en in E._CATEGORY_EN.items():
        assert en and en.isascii(), f"{vi!r} -> {en!r} is not plain English"


# ----------------------------------------------------------------- event labels
def test_event_label_prefers_type_then_class():
    assert E.event_label_en("DIVIDEND", "CASH_DIVIDEND") == "Cash dividend"
    assert E.event_label_en("FINANCIAL", "FINANCIAL_STATEMENT") == "Financial statements"
    assert E.event_label_en("MEETING", "AGM") == "Annual general meeting"
    # unknown type -> class label
    assert E.event_label_en("OWNERSHIP", "SOMETHING_NEW") == "Ownership change"
    # nothing usable -> generic, never Vietnamese
    assert E.event_label_en(None, None) == "Company event"


# --------------------------------------------------------------------- headline
def test_headline_exact_rules_with_period_token():
    t, exact = E.headline_en(
        "HPG: Giải trình biến động LNST trên BCTC quý 3/2025 so với cùng kỳ năm trước"
    )
    assert exact is True
    assert t == "Financial-statement variance explanation, Q3/2025 — HPG"

    t, exact = E.headline_en("VNM: Báo cáo tình hình quản trị công ty năm 2025")
    assert (t, exact) == ("Corporate governance report, 2025 — VNM", True)

    t, exact = E.headline_en("MSH: Báo cáo tình hình quản trị 6 tháng đầu năm 2026")
    assert t == "Corporate governance report, H1 2026 — MSH"

    t, exact = E.headline_en("CVPB2615: Thông báo về ngày giao dịch đầu tiên chứng quyền có bảo đảm")
    assert (t, exact) == ("Covered-warrant first trading day — CVPB2615", True)


def test_headline_symbol_argument_wins_over_prefix():
    t, _ = E.headline_en("HPG: Nghị quyết HĐQT", symbol="hpg")
    assert t.endswith("— HPG")


def test_headline_weak_rule_is_not_exact():
    t, exact = E.headline_en("VCB: Thông báo thay đổi Giấy phép thành lập và hoạt động")
    # matches the establishment-licence rule (strong), not the bare "Notice" weak rule
    assert exact is True
    t, exact = E.headline_en("ABC: Thông báo gửi cổ đông")
    assert (t, exact) == ("Notice — ABC", False)


def test_headline_fallback_is_honest_classification_never_fake_translation():
    t, exact = E.headline_en(
        "XYZ: Một nội dung công bố rất dài không khớp mẫu nào cả và cũng không có động từ dẫn",
        category="Tin Tổ chức niêm yết",
    )
    assert exact is False
    assert t == "Listed-issuer disclosure — XYZ"


def test_headline_empty_title():
    t, exact = E.headline_en(None, category="Tin quản lý thị trường", symbol="VNINDEX")
    assert (t, exact) == ("Market administration notice — VNINDEX", False)
    assert E.headline_en("   ")[1] is False


def test_headline_output_is_ascii():
    # a broad sweep of representative titles must never emit Vietnamese diacritics
    for title in [
        "HPG: Thông báo thay đổi giá trị tài sản ròng ngày 27/08/2026",
        "FUEKIV30: Thông báo về danh mục chứng khoán cơ cấu hoán đổi ngày 27/08/2026",
        "VPB: Báo cáo kết quả giao dịch cổ phiếu của người nội bộ",
        "SSI: Nghị quyết và Biên bản họp ĐHĐCĐ thường niên năm 2025",
        "MWG: Thông báo phát hành cổ phiếu để trả cổ tức",
        "ACB: Quyết định về việc hủy niêm yết chứng quyền có bảo đảm",
    ]:
        text, _ = E.headline_en(title)
        assert _no_vietnamese(text), f"{title!r} -> {text!r}"
