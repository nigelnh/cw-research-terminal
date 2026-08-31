"""Deterministic, zero-cost English presentation layer for the Vietnamese-canonical
research corpus.

CW Research Terminal is English-first (docs/design/LANGUAGE_POLICY.md). The HOSE feed is
Vietnamese at source and stays that way — the original ``title`` / ``summary_html`` /
``category`` are preserved verbatim for provenance. This module produces the *English*
face shown by default:

- ``category_en``     — a hand-written dictionary over every observed HOSE category. 100%
                        coverage; an unmapped value degrades to ``"HOSE disclosure"``.
- ``event_label_en``  — English label for an SSI / VNDirect company event, from the
                        already-English ``event_class`` / ``event_type`` enums.
- ``headline_en``     — keyword classification of the (highly templated) HOSE disclosure
                        title into a canonical English disclosure-type phrase, with the
                        period token (Q3/2025, H1 2026, 2025 …) carried through. Returns
                        ``(text, exact)`` — ``exact`` is False when no rule matched and we
                        fell back to ``"<category> — <SYMBOL>"``. We never fabricate a
                        precise translation of an out-of-pattern title.

No I/O, no network, no LLM, no paid API. Pure functions, unit-tested.
"""

from __future__ import annotations

import re

# --------------------------------------------------------------------------- category
# Every distinct HOSE `catName` observed in the 24-month corpus (2024-09 → 2026-08).
_CATEGORY_EN: dict[str, str] = {
    "Tin Tổ chức niêm yết": "Listed-issuer disclosure",
    "Tin quản lý thị trường": "Market administration notice",
    "Tin về hoạt động của Sở": "Exchange operations notice",
    "Điểm tin GD": "Trading briefing",
    "VNSI": "VNSI index notice",
    "Tin tức CW": "Covered-warrant news",
    "Danh sách tổng hợp tin tức vi phạm": "Consolidated violation list",
    "Tin hạn mức CW": "Covered-warrant offering-limit notice",
    "Tin tức": "News",
    "Tin tức về giao dịch ký quỹ": "Margin-trading notice",
    "Tin tức đấu giá": "Auction notice",
    "Tin tức khác": "Other news",
    "Báo cáo chỉ số định kỳ": "Periodic index report",
    "Hose News": "HOSE news",
    "Thông báo mời làm đại lý đấu giá": "Auction-agent invitation",
    "VLCA": "Listed-company disclosure",
    "Thị Phần Môi Giới": "Brokerage market share",
    "Tuyển dụng": "Recruitment notice",
    "Quy tắc các bộ chỉ số": "Index rulebook",
    "Tin CTY CKTV": "Member-firm notice",
    "Lịch giao dịch": "Trading calendar",
    "Góc Nhà đầu tư": "Investor corner",
    "HOSE - 25 năm hoạt động": "HOSE 25th anniversary",
    "News on margin trading": "Margin-trading notice",
    "Theo bộ chỉ số": "By index set",
    "CK Không được phép GDKQ": "Margin-ineligible securities",
    "Biểu giá dịch vụ": "Service fee schedule",
    "General information": "General information",
    "Cơ cấu tổ chức": "Organisational structure",
    "Other": "Other",
}

_CATEGORY_FALLBACK = "HOSE disclosure"


def category_en(vi: str | None) -> str:
    """English label for a HOSE category. Deterministic; unmapped -> a safe generic."""
    if not vi:
        return _CATEGORY_FALLBACK
    return _CATEGORY_EN.get(vi.strip(), _CATEGORY_FALLBACK)


# ---------------------------------------------------------------------- company events
_EVENT_CLASS_LABELS: dict[str, str] = {
    "DIVIDEND": "Dividend",
    "RIGHTS": "Rights issue",
    "MEETING": "Shareholder meeting",
    "LISTING": "Listing",
    "FINANCIAL": "Financial disclosure",
    "OWNERSHIP": "Ownership change",
    "OTHER": "Company event",
}

_EVENT_TYPE_LABELS: dict[str, str] = {
    "CASH_DIVIDEND": "Cash dividend",
    "STOCK_DIVIDEND": "Stock dividend",
    "BONUS_ISSUE": "Bonus share issue",
    "RIGHTS_ISSUE": "Rights issue",
    "FINANCIAL_STATEMENT": "Financial statements",
    "LISTING": "New listing",
    "ADDITIONAL_LISTING": "Additional listing",
    "DELISTING": "Delisting",
    "AGM": "Annual general meeting",
    "EGM": "Extraordinary general meeting",
    "MEETING": "Shareholder meeting",
    "INSIDER_TRANSACTION": "Insider transaction",
    "MAJOR_HOLDER_TRANSACTION": "Major-holder transaction",
    "OWNERSHIP": "Ownership change",
    "OTHER": "Company event",
}


def event_class_label_en(event_class: str | None) -> str:
    """English label for an event_class enum (the feed 'category' for event rows)."""
    if event_class:
        return _EVENT_CLASS_LABELS.get(event_class.strip().upper(), "Company event")
    return "Company event"


def event_label_en(event_class: str | None, event_type: str | None) -> str:
    """English display label for a company event, from the English enums.

    Prefers the specific ``event_type``; falls back to the ``event_class``; never the raw
    Vietnamese ``event_name``.
    """
    if event_type:
        lab = _EVENT_TYPE_LABELS.get(event_type.strip().upper())
        if lab:
            return lab
    if event_class:
        lab = _EVENT_CLASS_LABELS.get(event_class.strip().upper())
        if lab:
            return lab
    if event_type:
        return event_type.strip().upper().replace("_", " ").title()
    return "Company event"


# --------------------------------------------------------------------------- headline
# Period token: "quý 3/2025" -> "Q3/2025"; "6 tháng đầu năm 2026" -> "H1 2026";
# "bán niên 2025" -> "H1 2025"; "năm 2025" -> "2025".
_RE_QUARTER = re.compile(r"quý\s*([1-4])\s*[/-]?\s*(20\d{2})", re.I)
_RE_HALF = re.compile(r"(?:6\s*tháng\s*đầu\s*năm|bán\s*niên)\s*(20\d{2})", re.I)
_RE_YEAR = re.compile(r"năm\s*(20\d{2})", re.I)
_RE_BARE_YEAR = re.compile(r"\b(20\d{2})\b")
_RE_DMY = re.compile(r"\b(\d{1,2}[/-]\d{1,2}[/-]20\d{2})\b")


def _period_token(vi: str) -> str | None:
    m = _RE_QUARTER.search(vi)
    if m:
        return f"Q{m.group(1)}/{m.group(2)}"
    m = _RE_HALF.search(vi)
    if m:
        return f"H1 {m.group(1)}"
    m = _RE_DMY.search(vi)
    if m:
        return m.group(1).replace("-", "/")
    m = _RE_YEAR.search(vi) or _RE_BARE_YEAR.search(vi)
    if m:
        return m.group(1)
    return None


# Ordered keyword rules — first whose every marker is present (case-insensitive substring
# on the Vietnamese title) wins. Specific rules first. English is a canonical
# disclosure-type phrase, not a literal translation.
_TITLE_RULES: list[tuple[tuple[str, ...], str]] = [
    # --- covered warrants (order before generic "niêm yết"/"chứng quyền")
    (("hủy niêm yết", "chứng quyền"), "Covered-warrant delisting"),
    (("chấp thuận niêm yết", "chứng quyền"), "Covered-warrant listing approval"),
    (("thay đổi đăng ký niêm yết", "chứng quyền"), "Covered-warrant listing-registration change"),
    (("giao dịch đầu tiên", "chứng quyền"), "Covered-warrant first trading day"),
    (("điều chỉnh chứng quyền",), "Covered-warrant adjustment"),
    (("giá thanh toán", "chứng quyền"), "Covered-warrant settlement price"),
    (("giá thanh toán", "đáo hạn"), "Covered-warrant settlement price at maturity"),
    (("hạn mức", "chứng quyền"), "Covered-warrant offering-limit notice"),
    (("bản cáo bạch", "chứng quyền"), "Covered-warrant offering prospectus"),
    (("giấy chứng nhận", "chào bán", "chứng quyền"), "Covered-warrant offering registration certificate"),
    (("giấy chứng nhận đăng ký chào bán", "chứng quyền"), "Covered-warrant offering registration certificate"),
    (("điều chỉnh thông tin chứng quyền",), "Covered-warrant information adjustment"),
    (("đăng ký cuối cùng", "đáo hạn"), "Covered-warrant maturity record-date notice"),
    ((" đkcc", "đáo hạn"), "Covered-warrant maturity record-date notice"),
    # --- ETF / fund
    (("danh mục", "hoán đổi"), "ETF swap-portfolio notice"),
    (("kết thúc giao dịch hoán đổi",), "ETF swap-trading close"),
    (("giá trị tài sản ròng",), "ETF net asset value (NAV) notice"),
    (("sai lệch", "chỉ số tham chiếu"), "ETF tracking-error notice"),
    (("chứng chỉ quỹ", "kết quả giao dịch"), "Fund-certificate transaction result"),
    (("chứng chỉ quỹ", "giao dịch"), "Fund-certificate transaction notice"),
    (("niêm yết", "chứng chỉ quỹ"), "Fund-certificate listing change"),
    # --- financial statements / results
    (("giải trình", "lnst"), "Financial-statement variance explanation"),
    (("giải trình", "lợi nhuận"), "Financial-statement variance explanation"),
    (("giải trình", "bctc"), "Financial-statement explanation"),
    (("giải trình", "chênh lệch"), "Financial-statement variance explanation"),
    (("giải trình", "kết quả kinh doanh"), "Business-results variance explanation"),
    (("giải trình", "kết quả sxkd"), "Business-results variance explanation"),
    (("giải trình", "sxkd"), "Business-results variance explanation"),
    (("giải trình", "kết quả"), "Results-variance explanation"),
    (("giải trình",), "Explanatory statement"),
    (("kết quả kinh doanh",), "Business results"),
    (("kết quả sxkd",), "Business results"),
    (("điểm tin",), "Trading briefing"),
    (("báo cáo tài chính",), "Financial statements"),
    (("bctc",), "Financial statements"),
    (("hợp đồng kiểm toán",), "Audit-engagement notice"),
    (("đơn vị kiểm toán",), "Auditor selection"),
    (("công ty kiểm toán",), "Auditor selection"),
    (("báo cáo thường niên",), "Annual report"),
    (("bản cáo bạch", "cổ phiếu"), "Share-offering prospectus"),
    (("bản cáo bạch",), "Offering prospectus"),
    (("báo cáo hoạt động đầu tư",), "Investment-activity report"),
    (("cbtt",), "Information disclosure"),
    (("công bố thông tin", "người có liên quan"), "Related-party transaction disclosure"),
    # --- governance / AGM / consultation
    (("tình hình quản trị",), "Corporate governance report"),
    (("nghị quyết", "biên bản", "đhđcđ"), "AGM resolution and minutes"),
    (("biên bản", "nghị quyết", "đhđcđ"), "AGM minutes and resolution"),
    (("tài liệu", "đhđcđ"), "AGM meeting documents"),
    (("mời họp", "đhđcđ"), "AGM invitation"),
    (("thư mời", "đhđcđ"), "AGM invitation"),
    (("thư mời tham dự", "đhcđ"), "AGM invitation"),
    (("thông báo", "mời họp"), "General-meeting invitation"),
    (("đăng ký cuối cùng", "đhđcđ"), "AGM record-date notice"),
    (("đkcc", "đhđcđ"), "AGM record-date notice"),
    (("đăng ký cuối cùng", "đhcđ"), "AGM record-date notice"),
    (("lấy ý kiến cổ đông",), "Written shareholder consultation"),
    (("nghị quyết hđqt", "tổ chức họp"), "Board resolution on convening the AGM"),
    (("nghị quyết hđqt", "đhđcđ"), "Board resolution on the AGM"),
    (("nghị quyết hđqt", "kiểm toán"), "Board resolution on auditor selection"),
    (("nghị quyết hđqt", "trả cổ tức"), "Board resolution on a dividend"),
    (("nghị quyết hđqt", "phát hành cổ phiếu"), "Board resolution on a share issuance"),
    (("nghị quyết hđqt",), "Board resolution"),
    # --- dividends / issuance
    (("phát hành cổ phiếu", "trả cổ tức"), "Share issuance for a stock dividend"),
    (("kết quả", "phát hành cổ phiếu", "cổ tức"), "Stock-dividend issuance result"),
    (("trả cổ tức",), "Dividend payment notice"),
    (("chi trả cổ tức",), "Dividend payment notice"),
    (("phát hành cổ phiếu",), "Share issuance notice"),
    # --- insider / related-party / foreign ownership
    (("kết quả giao dịch", "tổ chức có liên quan"), "Related-party share-transaction result"),
    (("kết quả giao dịch", "người có liên quan"), "Related-party share-transaction result"),
    (("kết quả giao dịch", "người nội bộ"), "Insider share-transaction result"),
    (("kết quả giao dịch", "cổ phiếu"), "Share-transaction result"),
    (("giao dịch cổ phiếu", "tổ chức có liên quan"), "Related-party share-transaction notice"),
    (("giao dịch cổ phiếu", "người có liên quan"), "Related-party share-transaction notice"),
    (("giao dịch cổ phiếu", "người nội bộ"), "Insider share-transaction notice"),
    (("giao dịch chứng chỉ quỹ",), "Fund-certificate transaction notice"),
    (("thay đổi", "sở hữu", "nước ngoài"), "Foreign-ownership change report"),
    (("số liệu", "sở hữu", "nước ngoài"), "Foreign-ownership data"),
    (("báo cáo", "sở hữu",), "Ownership-change report"),
    (("cổ đông lớn",), "Major-shareholder notice"),
    # --- record dates (generic, after the specific AGM/warrant ones)
    (("đăng ký cuối cùng", "thực hiện quyền"), "Rights-exercise record-date notice"),
    (("đkcc", "thực hiện quyền"), "Rights-exercise record-date notice"),
    (("ngày đăng ký cuối cùng",), "Record-date notice"),
    (("đkcc",), "Record-date notice"),
    # --- listing (equity)
    (("hủy niêm yết",), "Delisting notice"),
    (("thay đổi đăng ký niêm yết",), "Listing-registration change"),
    (("thay đổi niêm yết",), "Listing change"),
    (("chấp thuận niêm yết",), "Listing approval"),
    (("niêm yết", "giao dịch"), "Listing and trading notice"),
    (("số lượng cổ phiếu", "biểu quyết"), "Change in voting shares outstanding"),
    # --- corporate admin
    (("thay đổi nhân sự",), "Personnel change"),
    (("từ nhiệm",), "Resignation notice"),
    (("bổ nhiệm",), "Appointment notice"),
    (("giấy chứng nhận đăng ký doanh nghiệp",), "Amended business-registration certificate"),
    (("đăng ký doanh nghiệp",), "Business-registration update"),
    (("đăng ký hoạt động", "văn phòng đại diện"), "Representative-office registration"),
    (("đăng ký hoạt động", "chi nhánh"), "Branch registration certificate"),
    (("đăng ký", "địa điểm kinh doanh"), "Business-location registration"),
    (("giấy phép", "thành lập và hoạt động"), "Establishment-and-operation licence change"),
    (("điều lệ",), "Company charter"),
    (("quy chế nội bộ về quản trị",), "Internal corporate-governance regulation"),
    (("quy chế hoạt động của hđqt",), "Board operating regulation"),
    (("quy chế hoạt động", "kiểm toán nội bộ"), "Internal-audit regulation"),
    (("quy chế",), "Internal regulation"),
    (("mẫu dấu",), "Company seal change"),
    # --- compliance / penalties
    (("xử phạt", "thuế"), "Tax-penalty notice"),
    (("xử phạt vi phạm",), "Administrative-penalty notice"),
    (("xử lý vi phạm",), "Violation-handling notice"),
    (("diện cảnh báo",), "Warning-list notice"),
    (("bị cảnh báo",), "Warning-list notice"),
    (("diện kiểm soát",), "Control-list notice"),
    (("bị kiểm soát",), "Control-list notice"),
    (("hạn chế giao dịch",), "Trading-restriction notice"),
    (("khắc phục", "chứng khoán bị"), "Remediation-plan explanation"),
    (("không đủ điều kiện giao dịch ký quỹ",), "Margin-ineligibility notice"),
    (("trái phiếu",), "Bond notice"),
]

# Weak rules: a leading-verb classification only (not a disclosure *type*). These return
# ``exact=False`` — the English is directionally right but the original title carries
# detail the label does not.
_WEAK_TITLE_RULES: list[tuple[tuple[str, ...], str]] = [
    (("thông báo",), "Notice"),
    (("báo cáo",), "Report"),
    (("quyết định",), "Decision"),
    (("nghị quyết",), "Resolution"),
    (("biên bản",), "Minutes"),
    (("công văn",), "Official letter"),
    (("công bố thông tin",), "Information disclosure"),
    (("tài liệu",), "Document"),
]


def _strip_symbol_prefix(title: str) -> tuple[str, str | None]:
    """`"HPG: Báo cáo …"` -> `("Báo cáo …", "HPG")`. No colon -> `(title, None)`."""
    if ":" in title:
        head, rest = title.split(":", 1)
        head = head.strip()
        if 1 <= len(head) <= 24 and " " not in head and head.upper() == head:
            return rest.strip(), head.upper()
    return title.strip(), None


def headline_en(
    title: str | None,
    *,
    category: str | None = None,
    symbol: str | None = None,
) -> tuple[str, bool]:
    """Return ``(english_headline, exact)`` for a HOSE disclosure title.

    ``exact`` is True when a disclosure-type rule matched (a confident canonical English
    rendering); False when we fell back to ``"<English category> — <SYMBOL>"``. The
    original Vietnamese title is never discarded — callers keep it as provenance.
    """
    if not title or not title.strip():
        cat = category_en(category)
        sym = (symbol or "").upper()
        return (f"{cat} — {sym}" if sym else cat, False)

    body, sym_from_title = _strip_symbol_prefix(title)
    sym = (symbol or sym_from_title or "").upper()
    low = body.lower()

    def _finish(label: str, exact: bool) -> tuple[str, bool]:
        period = _period_token(body)
        text = f"{label}, {period}" if period else label
        return (f"{text} — {sym}" if sym else text, exact)

    for markers, label in _TITLE_RULES:
        if all(m in low for m in markers):
            return _finish(label, True)

    for markers, label in _WEAK_TITLE_RULES:
        if all(m in low for m in markers):
            return _finish(label, False)

    # honest fallback: category classification only, no invented translation
    cat = category_en(category)
    return (f"{cat} — {sym}" if sym else cat, False)
