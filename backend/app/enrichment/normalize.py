"""Pure normalization: raw source payloads -> canonical row dicts. No I/O, no DB.

Kept deliberately independent of the old n8n prototype's numeric API codes. The public
domain language is a small, explicit vocabulary backed by data we actually receive.
"""

from __future__ import annotations

import hashlib
import html
import re
from datetime import date, datetime, timezone

_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9]{1,11}$")
_TAG_RE = re.compile(r"<[^>]+>")


# --------------------------------------------------------------------------- #
# HSX news
# --------------------------------------------------------------------------- #
def extract_symbols_from_title(title: str) -> list[str]:
    """HOSE disclosure titles are prefixed with the disclosing entity's code:
        ``MSH: ...``                     -> ['MSH']
        ``VHM.ACBS.8M.112 Term 8 ...``   -> ['VHM']   (dotted warrant/notice code)
        ``FUEABVND: ...``                -> ['FUEABVND']
    Returns [] when nothing before the first ':' / whitespace looks like a ticker."""
    if not title or ":" not in title:
        return []
    head = title.split(":", 1)[0].strip()
    if not head or len(head) > 40:
        return []
    first = head.split()[0] if head.split() else head
    # A real HOSE prefix is either a bare code ("MSH") or a dotted compound code
    # ("VHM.ACBS.8M.112 ..."). A prefix with spaces but no dot in the first token is a
    # sentence, not a ticker.
    if " " in head and "." not in first:
        return []
    parts = [p.strip() for p in first.split(".") if p.strip()]
    # Dotted compound codes ("VHM.ACBS.8M.112") name a CW/notice: the first component is
    # the primary listed entity; later components are the issuer / term and are not
    # standalone tradeable tickers.
    candidates = [parts[0]] if len(parts) > 1 else parts
    out: list[str] = []
    for p in candidates:
        pu = p.upper()
        if _TICKER_RE.fullmatch(pu) and pu not in out:
            out.append(pu)
    return out


def strip_html(s: str | None) -> str | None:
    if not s:
        return None
    text = _TAG_RE.sub(" ", s)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip() or None


def _epoch_to_dt(v) -> datetime | None:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    if n > 1_000_000_000_000:  # milliseconds
        n //= 1000
    return datetime.fromtimestamp(n, tz=timezone.utc)


def normalize_hsx_news(item: dict, *, lang: str, base_web: str = "https://www.hsx.vn") -> dict:
    title = str(item.get("title") or "").strip()
    nid = str(item.get("id") or "").strip()
    # HSX's API exposes no direct document/PDF link (`alias` / `link` are null even on the
    # detail endpoint). The canonical human-viewable page is the portal ViewArticle route
    # keyed by the numeric id, which embeds the PDF once its JS loads.
    alias = item.get("alias")
    if alias:
        url = f"{base_web}/Modules/CMS/Web/ViewArticle/{alias}"
    elif item.get("link"):
        url = str(item["link"])
    elif nid:
        url = f"{base_web}/Modules/CMS/Web/ViewArticle/{nid}"
    else:
        url = None
    cat_id = item.get("catId")
    try:
        cat_id = int(cat_id) if cat_id is not None else None
    except (TypeError, ValueError):
        cat_id = None
    # Full upstream payload is NOT persisted for news (0006) — HOSE is public and
    # re-fetchable by (source, source_id). Only the fields we don't otherwise normalize
    # and might want for re-parsing are carried on the row dict for the CLI's use.
    return {
        "source": "HOSE",
        "source_id": nid,
        "lang": lang,
        "content_type": "exchange_disclosure",
        "title": title[:1000],
        "summary_html": (str(item["summary"])[:8000] if item.get("summary") else None),
        # The list endpoint carries only a numeric catId; catName arrives from the detail
        # endpoint. The CLI backfills category names with one bounded detail call per
        # distinct catId (see enrichment/cli.py::_resolve_categories).
        "category": (str(item["catName"])[:200] if item.get("catName") else None),
        "cat_id": cat_id,
        "symbols": extract_symbols_from_title(title),
        "related_source_id": (str(item["relatedId"]) if item.get("relatedId") is not None else None),
        "published_at": _epoch_to_dt(item.get("publishFrom")) or _epoch_to_dt(item.get("postedDate")),
        "approved_at": _epoch_to_dt(item.get("approvedDate")),
        "url": (url[:1000] if url else None),
    }


# --------------------------------------------------------------------------- #
# VNDirect corporate events
# --------------------------------------------------------------------------- #
_STOCK_DIV_HINT = re.compile(r"cổ phiếu|by share|stock dividend|bằng cp|bằng cổ phiếu", re.I)
_CASH_DIV_HINT = re.compile(r"tiền mặt|bằng tiền|by cash|cash dividend|đ/cp|vnd/share", re.I)
_RIGHTS_HINT = re.compile(r"quyền mua|rights issue|chào bán|phát hành thêm cho cổ đông", re.I)
_BONUS_HINT = re.compile(r"cổ phiếu thưởng|bonus share|thưởng cổ phiếu", re.I)
_AGM_HINT = re.compile(r"thường niên|annual general meeting|ĐHĐCĐ TN|AGM", re.I)
_EGM_HINT = re.compile(r"bất thường|extraordinary|EGM", re.I)


def _parse_iso_date(v) -> date | None:
    if not v:
        return None
    s = str(v).strip()[:10]
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_ddmmyyyy(v) -> date | None:
    """SSI dates are ``DD/MM/YYYY``."""
    if not v:
        return None
    s = str(v).strip()[:10]
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


# event_type -> event_class (the price-adjustment / meeting / disclosure discriminator)
_EVENT_CLASS: dict[str, str] = {
    "CASH_DIVIDEND": "DIVIDEND",
    "STOCK_DIVIDEND": "DIVIDEND",
    "BONUS_ISSUE": "DIVIDEND",
    "RIGHTS_ISSUE": "RIGHTS",
    "AGM": "MEETING",
    "EGM": "MEETING",
    "LISTING": "LISTING",
    "DELISTING": "LISTING",
    "ADDITIONAL_LISTING": "LISTING",
    "FINANCIAL_STATEMENT": "FINANCIAL",
    "INSIDER_TRANSACTION": "OWNERSHIP",
    "OTHER": "OTHER",
}


def event_class_for(event_type: str) -> str:
    return _EVENT_CLASS.get(event_type, "OTHER")


def classify_vndirect_event(item: dict) -> tuple[str, str]:
    """Returns (action_type, status)."""
    typ = str(item.get("type") or "").strip()
    group = str(item.get("group") or "").strip()
    note = str(item.get("note") or "") + " " + str(item.get("typeDesc") or "")

    status = "CONFIRMED"
    if group == "schedEvent" or typ.startswith("sched"):
        status = "SCHEDULED"

    if _RIGHTS_HINT.search(note):
        return "RIGHTS_ISSUE", status
    if _BONUS_HINT.search(note):
        return "BONUS_ISSUE", status
    if typ in ("schedDiv", "DIV", "DIVIDEND") or "cổ tức" in note.lower() or "dividend" in note.lower():
        if _STOCK_DIV_HINT.search(note):
            return "STOCK_DIVIDEND", status
        if _CASH_DIV_HINT.search(note) or item.get("dividend"):
            return "CASH_DIVIDEND", status
        # a bare ratio without "cash" wording is a share distribution
        if item.get("ratio") and not item.get("dividend"):
            return "STOCK_DIVIDEND", status
        return "CASH_DIVIDEND", status
    if typ in ("MEETING", "GMS") or group == "investorRight":
        if _EGM_HINT.search(note):
            return "EGM", "SCHEDULED" if status == "SCHEDULED" else "CONFIRMED"
        if _AGM_HINT.search(note) or "họp" in note.lower() or "meeting" in note.lower():
            return "AGM", "SCHEDULED" if status == "SCHEDULED" else "CONFIRMED"
    typ_l = typ.lower()
    note_l = note.lower()
    if "delisting" in typ_l or "hủy niêm yết" in note_l or "hủy đăng ký" in note_l:
        return "DELISTING", status
    if (
        "listed" in typ_l  # VNDirect: "LISTED" / "updateListed" (additional issuance)
        or "listing" in typ_l
        or "niêm yết" in note_l
        or "bổ sung" in note_l  # "NY bổ sung" / "GD bổ sung"
        or "listing" in note_l
    ):
        return "LISTING", status
    return "OTHER", status


def _num(v):
    try:
        f = float(v)
        return f if f == f else None  # drop NaN
    except (TypeError, ValueError):
        return None


def normalize_vndirect_event(item: dict) -> dict | None:
    raw_id = str(item.get("id") or "").strip()
    if not raw_id:
        return None
    # ids look like "124861.VN" / "124861.EN_GB" for the same event across locales.
    source_id = raw_id.split(".", 1)[0]
    symbol = str(item.get("code") or "").strip().upper()
    if not symbol:
        return None
    action_type, status = classify_vndirect_event(item)

    dividend = _num(item.get("dividend"))
    ratio = _num(item.get("ratio"))
    div_year = None
    try:
        div_year = int(item["divYear"]) if item.get("divYear") is not None else None
    except (TypeError, ValueError):
        div_year = None

    ratio_text = None
    if ratio is not None:
        # "rate 100:10" style if present in the note, else derive
        m = re.search(r"(\d+\s*:\s*\d+)", str(item.get("note") or ""))
        ratio_text = m.group(1).replace(" ", "") if m else f"100:{ratio:g}"

    disclosure = _parse_iso_date(item.get("disclosureDate"))
    return {
        "source": "VNDIRECT",
        "source_id": source_id,
        "symbol": symbol[:32],
        "event_type": action_type,
        "event_class": event_class_for(action_type),
        "event_name": (str(item.get("typeDesc"))[:200] if item.get("typeDesc") else None),
        "source_event_code": (str(item.get("type"))[:40] if item.get("type") else None),
        "status": status,
        "ex_date": _parse_iso_date(item.get("effectiveDate")),
        "record_date": _parse_iso_date(item.get("expiredDate")) or _parse_iso_date(item.get("effectiveDate")),
        "payment_date": _parse_iso_date(item.get("actualDate")) or _parse_iso_date(item.get("paymentDate")),
        "disclosure_date": disclosure,
        "public_date": disclosure,
        "cash_amount_vnd": dividend,
        "ratio_pct": ratio,
        "ratio_text": (ratio_text[:64] if ratio_text else None),
        "value_text": None,
        "dividend_year": div_year,
        "note": (str(item.get("note") or item.get("typeDesc") or "")[:2000] or None),
        "url": None,
        "raw": item,
    }


# --------------------------------------------------------------------------- #
# SSI structured company events (iboard-api statistics/company/ssmi/corporate-actions)
# --------------------------------------------------------------------------- #
# eventListCode -> (event_type, event_class). SSI's taxonomy is broader than corporate
# actions: it includes financial-statement disclosures and insider transactions.
_SSI_EVENT_MAP: dict[str, tuple[str, str]] = {
    "KQQY": ("FINANCIAL_STATEMENT", "FINANCIAL"),   # quarterly results
    "KQCT": ("FINANCIAL_STATEMENT", "FINANCIAL"),   # audited / parent-company results
    "KQNAM": ("FINANCIAL_STATEMENT", "FINANCIAL"),
    "DDRP": ("INSIDER_TRANSACTION", "OWNERSHIP"),   # related-party dealing
    "DDALL": ("INSIDER_TRANSACTION", "OWNERSHIP"),  # insider / major-holder dealing
    "GDCP": ("INSIDER_TRANSACTION", "OWNERSHIP"),
    "AGME": ("AGM", "MEETING"),
    "GDCD": ("EGM", "MEETING"),
    "ISS": ("ADDITIONAL_LISTING", "LISTING"),       # share issuance / additional listing
    "AIS": ("ADDITIONAL_LISTING", "LISTING"),
    "LIS": ("LISTING", "LISTING"),
    "DELIST": ("DELISTING", "LISTING"),
}

_SSI_CASH_DIV = re.compile(r"cổ tức.*tiền|tiền mặt|bằng tiền|by cash|cash dividend|đ/cp|đ/cổ phần", re.I)
_SSI_STOCK_DIV = re.compile(
    r"cổ tức.*cổ phiếu|cổ phiếu.*cổ tức|phát hành cổ phiếu để trả|trả cổ tức bằng cổ phiếu"
    r"|by shares?|stock dividend|dividend.*shares?",
    re.I,
)
_SSI_BONUS = re.compile(r"cổ phiếu thưởng|bonus", re.I)
_SSI_RIGHTS = re.compile(r"quyền mua|rights|phát hành thêm cho cổ đông hiện hữu", re.I)
_SSI_AGM = re.compile(r"thường niên|annual", re.I)
_SSI_EGM = re.compile(r"bất thường|extraordinary", re.I)


def classify_ssi_event(item: dict) -> tuple[str, str]:
    """Returns (event_type, event_class) for an SSI company event.

    ``eventListCode`` is the primary signal; the title text disambiguates dividends and
    meetings. An event with an ``exrightDate`` is NOT automatically a price adjustment —
    an AGM carries one too.
    """
    code = str(item.get("eventListCode") or "").strip().upper()
    title = f"{item.get('eventTitle') or ''} {item.get('eventName') or ''} {item.get('eventDescription') or ''}"
    cash = _num(item.get("value")) or 0
    ratio = _num(item.get("ratio")) or 0

    def _dividend_kind() -> tuple[str, str]:
        # explicit wording wins; else the numeric shape (a cash value => cash)
        if _SSI_STOCK_DIV.search(title):
            return "STOCK_DIVIDEND", "DIVIDEND"
        if _SSI_CASH_DIV.search(title) or "đ/cp" in title.lower():
            return "CASH_DIVIDEND", "DIVIDEND"
        if cash > 0:
            return "CASH_DIVIDEND", "DIVIDEND"
        if ratio > 0:
            return "STOCK_DIVIDEND", "DIVIDEND"
        return "CASH_DIVIDEND", "DIVIDEND"

    if code == "ISS" or code == "AIS":
        # a share-issuance event that is really a dividend / bonus distribution
        if _SSI_BONUS.search(title):
            return "BONUS_ISSUE", "DIVIDEND"
        if _SSI_RIGHTS.search(title):
            return "RIGHTS_ISSUE", "RIGHTS"
        if "cổ tức" in title.lower() or "dividend" in title.lower():
            return _dividend_kind()
        return "ADDITIONAL_LISTING", "LISTING"

    if code in _SSI_EVENT_MAP:
        et, ec = _SSI_EVENT_MAP[code]
        if code == "AGME" and _SSI_EGM.search(title):
            return "EGM", "MEETING"
        return et, ec

    tl = title.lower()
    if "cổ tức" in tl or "dividend" in tl:
        return _dividend_kind()
    if _SSI_RIGHTS.search(title):
        return "RIGHTS_ISSUE", "RIGHTS"
    if _SSI_BONUS.search(title):
        return "BONUS_ISSUE", "DIVIDEND"
    if _SSI_EGM.search(title):
        return "EGM", "MEETING"
    if _SSI_AGM.search(title) or "đhđcđ" in tl or "đại hội" in tl:
        return "AGM", "MEETING"
    if "niêm yết" in tl or "listing" in tl:
        return "LISTING", "LISTING"
    if "giao dịch nội bộ" in tl or "insider" in tl:
        return "INSIDER_TRANSACTION", "OWNERSHIP"
    if "bctc" in tl or "báo cáo tài chính" in tl or "financial statement" in tl:
        return "FINANCIAL_STATEMENT", "FINANCIAL"
    return "OTHER", "OTHER"


def ssi_event_key(item: dict) -> str:
    """Deterministic identity for an SSI event. ``eventCode`` is usually null, so hash the
    normalized identifying fields. Stable across re-crawls and locales."""
    parts = [
        str(item.get("symbol") or "").strip().upper(),
        str(item.get("eventListCode") or "").strip().upper(),
        _norm_ws(str(item.get("eventTitle") or "")).lower(),
        str(item.get("publicDate") or "").strip(),
        str(item.get("issueDate") or "").strip(),
        str(item.get("exrightDate") or "").strip(),
        str(item.get("recordDate") or "").strip(),
    ]
    digest = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:24]
    return f"ssi_{digest}"


def _norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def normalize_ssi_event(item: dict) -> dict | None:
    symbol = str(item.get("symbol") or "").strip().upper()
    if not symbol:
        return None
    title = _norm_ws(str(item.get("eventTitle") or item.get("eventDescription") or ""))
    if not title:
        return None
    event_type, event_class = classify_ssi_event(item)

    ratio_raw = str(item.get("ratio") or "").strip()
    ratio_pct = _num(ratio_raw)
    if ratio_pct == 0:
        ratio_pct = None
    value_raw = str(item.get("value") or "").strip()
    cash = _num(value_raw)
    if cash == 0:
        cash = None

    ex_date = _parse_ddmmyyyy(item.get("exrightDate"))
    public_date = _parse_ddmmyyyy(item.get("publicDate")) or _parse_ddmmyyyy(item.get("issueDate"))
    source_code = str(item.get("eventCode") or "").strip() or None

    div_year = None
    m = re.search(r"20\d{2}", title)
    if m and event_class in ("DIVIDEND", "MEETING"):
        div_year = int(m.group(0))

    return {
        "source": "SSI",
        "source_id": ssi_event_key(item),
        "symbol": symbol[:32],
        "event_type": event_type,
        "event_class": event_class,
        "event_name": (str(item.get("eventName"))[:200] if item.get("eventName") else None),
        "source_event_code": (source_code[:40] if source_code else str(item.get("eventListCode") or "")[:40] or None),
        "status": "CONFIRMED",
        "ex_date": ex_date,
        "record_date": _parse_ddmmyyyy(item.get("recordDate")),
        "payment_date": None,
        "disclosure_date": public_date,
        "public_date": public_date,
        "cash_amount_vnd": cash,
        "ratio_pct": ratio_pct,
        "ratio_text": (ratio_raw[:64] if ratio_raw and ratio_raw != "0" else None),
        "value_text": (value_raw[:120] if value_raw and value_raw != "0" else None),
        "dividend_year": div_year,
        "note": (_norm_ws(str(item.get("eventDescription") or ""))[:2000] or title[:2000]),
        "url": None,
        "raw": item,
    }


# --------------------------------------------------------------------------- #
# VNDirect company profile
# --------------------------------------------------------------------------- #
def _int(v):
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return None


def normalize_vndirect_profile(item: dict) -> dict | None:
    code = str(item.get("code") or "").strip().upper()
    if not code:
        return None
    return {
        "symbol": code[:32],
        "exchange": (str(item["floor"])[:16] if item.get("floor") else None),
        "vn_name": (str(item["vnName"])[:300] if item.get("vnName") else None),
        "en_name": (str(item["enName"])[:300] if item.get("enName") else None),
        "industry": (str(item.get("industryName") or item.get("icbName") or "")[:200] or None),
        "found_date": _parse_iso_date(item.get("foundDate")),
        "tax_code": (str(item["taxCode"])[:32] if item.get("taxCode") else None),
        "website": (str(item["website"])[:300] if item.get("website") else None),
        "listed_shares": _int(item.get("listedShare") or item.get("listedShares")),
        "outstanding_shares": _int(item.get("outstandingShare") or item.get("outstandingShares")),
        "source": "VNDIRECT",
        "source_id": code,
        "raw": item,
    }
