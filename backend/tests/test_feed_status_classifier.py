"""The provider-error classifier is fed CAPTURED SDK STDOUT, not just exception strings.

That output is full of tickers, prices and volumes, and the first implementation tested for
bare substrings: "no bars for HPG at 21500" classified as a 500, and "volume 1403000" as a
403. A false DATASET_FORBIDDEN blocks that scope for 900 seconds, so a price containing the
digits 403 could have taken a panel dark for a quarter of an hour.
"""
import pytest

from app.market_data.feed_status import (
    FeedAccess, MESSAGES, classify_provider_error, redact_provider_text,
)


# Strings captured verbatim from production logs on 2026-09-07/08.
@pytest.mark.parametrize("text,expected", [
    ("FiinQuant VN30 constituents unavailable: Service has expired.", "ENTITLEMENT_EXPIRED"),
    ("401, message='Unauthorized', url='https://apigw.fiingroup.vn/FXMA/TradingData'", "AUTH_REQUIRED"),
    ("Permisson error fetching data for ticker None at page 1 with url ...: "
     "You do not have permission to access this API.", "DATASET_FORBIDDEN"),
    ("You do not have permission to access MarketBreadth.", "DATASET_FORBIDDEN"),
    ("Historical authentication failure for CVPB2623. Circuit breaker OPEN for 60s: 401", "AUTH_REQUIRED"),
    ("upstream error 503", "UPSTREAM_UNAVAILABLE"),
    ("status=429", "RATE_LIMITED"),
    ("Read timeout", "UPSTREAM_UNAVAILABLE"),
])
def test_real_provider_failures_are_classified(text, expected):
    assert classify_provider_error(text) == expected


# Market data that flows through the same classifier and must never trip it.
@pytest.mark.parametrize("text", [
    "no bars for HPG at 21500 on 2026-09-07",
    "CHPG2617 volume 1403000",
    "VN30 close 1963.01 volume 210080000",
    "fetched 429 rows for CVPB2611",
    "CVPB2615 1,238,000 @ 790",
    "HPG O 21800 H 22150 L 21550 C 21550 V 19957800",
])
def test_prices_and_volumes_are_not_status_codes(text):
    assert classify_provider_error(text) is None


def test_a_status_code_still_needs_failure_context():
    """The numeric path is a backstop; the textual markers carry the real cases."""
    assert classify_provider_error("429") is None
    assert classify_provider_error("http 429") == "RATE_LIMITED"


def test_expiry_outranks_the_401_it_arrives_with():
    """An expired entitlement also 401s. Reporting AUTH_REQUIRED would send the operator
    to re-authenticate, which cannot fix it."""
    assert classify_provider_error(
        "401 Unauthorized: Service has expired."
    ) == "ENTITLEMENT_EXPIRED"


def test_nothing_recognisable_stays_unclassified():
    assert classify_provider_error("") is None
    assert classify_provider_error(None) is None
    assert classify_provider_error("no rows returned") is None


# --------------------------------------------------------------------------- redaction
def test_a_bearer_token_never_survives_redaction():
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abc-DEF_123"
    for text in (jwt, f"Authorization: Bearer {jwt}", f"failed with access_token={jwt}"):
        assert jwt not in redact_provider_text(text)
        assert "[redacted]" in redact_provider_text(text)


def test_redaction_keeps_the_diagnosis_intact():
    out = redact_provider_text("401 Unauthorized for url=https://apigw.fiingroup.vn/x")
    assert "401" in out and "Unauthorized" in out


# --------------------------------------------------------------------------- scoping
def test_one_forbidden_dataset_does_not_black_out_the_whole_feed():
    """MarketBreadth and BasicInfor are 403 on this tier permanently. Treating that as a
    feed-wide outage would hide every panel that still works."""
    access = FeedAccess()
    access.record("market_breadth", "You do not have permission to access MarketBreadth.")
    assert access.blocked("market_breadth") == "DATASET_FORBIDDEN"
    assert access.blocked("history") is None


def test_an_expired_entitlement_is_feed_wide():
    access = FeedAccess()
    access.record("history", "Service has expired.")
    assert access.blocked("overview") == "ENTITLEMENT_EXPIRED"


def test_a_success_clears_the_feed_wide_block_but_not_a_dataset_one():
    access = FeedAccess()
    access.record("history", "Service has expired.")
    access.record("market_breadth", "403 forbidden")
    access.success("history")
    assert access.blocked("overview") is None
    assert access.blocked("market_breadth") == "DATASET_FORBIDDEN"


def test_the_wire_shape_never_carries_internal_retry_clocks():
    access = FeedAccess()
    access.record("history", "Service has expired.")
    wire = access.wire(fresh=False, active=True, last_data_at="2026-09-07T14:45:00+07:00")
    assert wire["code"] == "ENTITLEMENT_EXPIRED"
    assert wire["message"] == MESSAGES["ENTITLEMENT_EXPIRED"]
    assert wire["lastDataAt"] == "2026-09-07T14:45:00+07:00"
    assert "retryAt" not in wire
    assert all("retryAt" not in d for d in wire["datasets"])
