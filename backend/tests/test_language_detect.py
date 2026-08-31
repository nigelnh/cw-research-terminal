"""Reply-language detection — accented VI, un-accented VI, teencode, English, ambiguous."""

from __future__ import annotations

import pytest

from app.ai.language_detect import detect_language, detect_reply_language


VI = [
    # accented
    "HPG tăng vì sao?",
    "HPG gần đây có tin gì?",
    "cổ tức của HPG thế nào?",
    # un-accented
    "HPG co tin gi moi ko?",
    "HPG gan day sao roi?",
    "co su kien gi moi khong?",
    "m coi thu con nay sao",
    "HPG tang vi sao?",
    "HPG gan day co tin gi?",
    "gio HPG sao roi",
    "co gi moi ko?",
    "check HPG IV giup t voi",
    "phan tich giup HPG hom nay",
    "HPG co nen mua khong?",
]

EN = [
    "What's new with HPG?",
    "HPG news?",
    "Can you check HPG?",
    "what about HPG after the dividend?",
    "compare HPG IV vs HV",
    "why is IV high?",
    "What about its recent dividend?",
    "Summarize HPG's latest disclosures and compare the recent price action.",
    "HPG",
    "HPG?",
    "show me delta and gamma for CVPB2615",
    "is the market open right now?",
]


@pytest.mark.parametrize("msg", VI)
def test_vietnamese_messages(msg):
    assert detect_language(msg) == "vi", msg


@pytest.mark.parametrize("msg", EN)
def test_english_messages(msg):
    assert detect_language(msg) == "en", msg


def test_ambiguous_and_empty_default_to_english():
    assert detect_language("") == "en"
    assert detect_language(None) == "en"
    assert detect_language("   ") == "en"
    assert detect_language("HPG data") == "en"        # one weak-ish token, not enough
    assert detect_language("hi") == "en"


def test_latest_message_only_via_wrapper():
    assert detect_reply_language("How is it different from historical volatility?") == "English"
    assert detect_reply_language("Còn HPG thì sao?") == "Vietnamese"
    assert detect_reply_language("con HPG thi sao?") == "Vietnamese"


def test_urls_and_code_do_not_flip_language():
    # a URL with vietnamese-looking path segments must not force VI
    assert detect_language("see https://hsx.vn/tin-tuc-cong-bo-thong-tin for the filing") == "en"
    assert detect_language("run `khong ko vay gi` then tell me the delta") == "en"
