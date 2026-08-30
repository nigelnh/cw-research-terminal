"""Pure normalization: raw source payloads -> canonical row dicts. No I/O, no DB.

Kept deliberately independent of the old n8n prototype's numeric API codes. The public
domain language is a small, explicit vocabulary backed by data we actually receive.
"""

from __future__ import annotations

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
    alias = item.get("alias")
    url = None
    if alias:
        url = f"{base_web}/Modules/CMS/Web/ViewArticle/{alias}"
    elif item.get("link"):
        url = str(item["link"])
    return {
        "source": "HSX",
        "source_id": nid,
        "lang": lang,
        "title": title[:1000],
        "summary_html": (str(item["summary"])[:8000] if item.get("summary") else None),
        "category": (str(item["catName"])[:200] if item.get("catName") else None),
        "symbols": extract_symbols_from_title(title),
        "related_source_id": (str(item["relatedId"]) if item.get("relatedId") is not None else None),
        "published_at": _epoch_to_dt(item.get("publishFrom")) or _epoch_to_dt(item.get("postedDate")),
        "approved_at": _epoch_to_dt(item.get("approvedDate")),
        "url": (url[:1000] if url else None),
        "raw": item,
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

    return {
        "source": "VNDIRECT",
        "source_id": source_id,
        "symbol": symbol[:32],
        "action_type": action_type,
        "status": status,
        "ex_date": _parse_iso_date(item.get("effectiveDate")),
        "record_date": _parse_iso_date(item.get("expiredDate")) or _parse_iso_date(item.get("effectiveDate")),
        "payment_date": _parse_iso_date(item.get("actualDate")) or _parse_iso_date(item.get("paymentDate")),
        "disclosure_date": _parse_iso_date(item.get("disclosureDate")),
        "cash_amount_vnd": dividend,
        "ratio_pct": ratio,
        "ratio_text": (ratio_text[:64] if ratio_text else None),
        "dividend_year": div_year,
        "note": (str(item.get("note") or item.get("typeDesc") or "")[:1000] or None),
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
