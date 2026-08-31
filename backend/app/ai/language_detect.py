"""Deterministic, high-precision reply-language detection.

Used only on the user's OWN latest substantive message — never thread history, retrieved
HOSE/SSI/VNDirect text, the selected symbol, or tool output. Default when ambiguous is
English (the product is English-first).

Two signals:
  1. Vietnamese-specific diacritics  -> Vietnamese (near-perfect precision).
  2. Un-accented Vietnamese lexical cues, weighted, above a threshold -> Vietnamese.
     Cues are chosen to NOT collide with ordinary English finance chat, and a single
     ambiguous token is never enough.

No external library — a small curated cue table.
"""

from __future__ import annotations

import re

# --- signal 1: Vietnamese-specific letters (đ + toned vowels) -----------------
_VN_DIACRITICS = set(
    "đàáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵ"
)

# --- signal 2: un-accented Vietnamese cues ------------------------------------
# Single tokens that are almost never a standalone lowercase word in an English finance
# question. Deliberately EXCLUDES English-colliding words (the, can, la, an, o, day, hay,
# so, no, in, on, to, is …). weight 2.
_VN_STRONG_TOKENS = {
    "khong", "ko", "hok", "kg", "vay", "dc", "duoc", "nhung", "roi", "nua", "chua",
    "gi", "sao", "voi", "cua", "nay", "nao", "moi", "hoi", "biet", "xem", "coi",
    "muon", "giup", "dang", "boi", "thi", "khi", "nhieu", "minh", "trc", "vao",
    "ntn",
}
# Weaker cues — real Vietnamese words that also brush English abbreviations / teencode.
# weight 1. Kept tiny on purpose.
_VN_WEAK_TOKENS = {"co", "con", "gio", "t", "m", "k", "de", "bi", "hot"}

# Multi-word phrases (checked as spaced substrings). Extremely un-English. weight 3.
_VN_PHRASES = (
    "gan day", "hom nay", "the nao", "nhu nao", "nhu the nao", "tai sao", "vi sao",
    "bao nhieu", "co gi", "co tin", "tin gi", "gi moi", "moi khong", "moi ko",
    "dc khong", "dc ko", "duoc khong", "duoc ko", "co su kien", "su kien gi",
    "su kien", "co gi moi", "coi thu", "giup t", "giup m", "giup minh", "giup voi",
    "the thi", "gio sao", "sao roi", "the la sao", "vay la sao", "lam sao", "lam the nao",
    "co nen", "nen mua", "nen ban", "the nay", "ra sao", "co phai", "phai khong",
    "dung khong", "y kien", "danh gia", "phan tich giup", "hom qua", "bua nay",
    "the la", "sao ko", "sao khong", "kieu gi", "con nay", "ma nay",
)

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_URL_RE = re.compile(r"https?://\S+|www\.\S+")
_CODE_RE = re.compile(r"`{1,3}[^`]*`{1,3}")
# obvious ticker/identifier shapes to drop before scoring (CW code, upper ticker)
_TICKER_RE = re.compile(r"\bC[A-Z0-9]{7}\b|\b[A-Z]{2,}[0-9]{0,4}\b")

_VI_SCORE_THRESHOLD = 3


def _normalize(text: str) -> tuple[str, list[str]]:
    """Return (spaced-lowercase-no-tickers, token list). Original casing already lost."""
    no_url = _URL_RE.sub(" ", text)
    no_code = _CODE_RE.sub(" ", no_url)
    no_ticker = _TICKER_RE.sub(" ", no_code)
    low = no_ticker.lower()
    tokens = _TOKEN_RE.findall(low)
    return " " + " ".join(tokens) + " ", tokens


def vi_score(text: str) -> int:
    """Weighted un-accented Vietnamese evidence. 0 for clean English."""
    spaced, tokens = _normalize(text)
    tokset = set(tokens)
    score = 0
    for ph in _VN_PHRASES:
        if f" {ph} " in spaced:
            score += 3
    score += 2 * len(tokset & _VN_STRONG_TOKENS)
    score += 1 * len(tokset & _VN_WEAK_TOKENS)
    return score


def detect_language(text: str | None) -> str:
    """``"vi"`` or ``"en"`` (default) from the user's own latest message only."""
    if not text or not text.strip():
        return "en"
    if _VN_DIACRITICS & set(text.lower()):
        return "vi"
    return "vi" if vi_score(text) >= _VI_SCORE_THRESHOLD else "en"


def detect_reply_language(latest_user_message: str | None) -> str:
    """Prompt-facing wrapper: ``"Vietnamese"`` / ``"English"``."""
    return "Vietnamese" if detect_language(latest_user_message) == "vi" else "English"
