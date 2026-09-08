"""The provider-error classifier is fed CAPTURED SDK STDOUT, not just exception strings.

That output is full of tickers, prices and volumes, and the first implementation tested for
bare substrings: "no bars for HPG at 21500" classified as a 500, and "volume 1403000" as a
403. A false DATASET_FORBIDDEN blocks that scope for 900 seconds, so a price containing the
digits 403 could have taken a panel dark for a quarter of an hour.
"""
import base64
import json

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


# --------------------------------------------------------------------------- wording
def test_the_expiry_notice_reports_what_was_observed_and_prescribes_nothing():
    """An earlier wording told the operator the account "needs renewal". That was a guess
    about FiinQuant's product, not something this server observed - the evidence shows only
    that the entitlement window ended and that logging in again does not extend it. A
    header that prescribes the wrong remedy is worse than one that reports the fact."""
    text = MESSAGES["ENTITLEMENT_EXPIRED"].lower()
    for prescription in ("renew", "renewal", "subscribe", "upgrade", "pay", "contact"):
        assert prescription not in text, f"message prescribes a remedy: {prescription!r}"
    assert "not active" in text


def test_the_end_date_is_carried_when_it_is_known():
    """The date is the one fact that makes the notice actionable, and it is not sensitive."""
    access = FeedAccess()
    access.record("history", "Service has expired.", detail="Access ended 2026-09-07.")
    assert "2026-09-07" in access.wire(fresh=False, active=True, last_data_at=None)["message"]


def test_it_reads_correctly_without_a_date():
    access = FeedAccess()
    access.record("history", "Service has expired.")
    message = access.wire(fresh=False, active=True, last_data_at=None)["message"]
    assert message == MESSAGES["ENTITLEMENT_EXPIRED"]
    assert not message.endswith(" ")


def test_no_token_claim_other_than_the_end_date_can_reach_the_wire():
    """inspect_session decodes a JWT; only the expiry may leave the process."""
    access = FeedAccess()
    access.record("history", "Service has expired.", detail="Access ended 2026-09-07.")
    blob = json.dumps(access.wire(fresh=False, active=True, last_data_at=None))
    for claim in ("xuannhan", "@", "CUSTOMER", "FiinQuant.Trial", "eyJ", "Individual"):
        assert claim not in blob


# --------------------------------------------------------------------------- #
# A token claim is evidence, not a verdict.
#
# `inspect_session` used to call `record()`, so a date field in a JWT became an
# authorization decision: `blocked()` gates every SDK call and the stream startup, and the
# app stopped contacting the provider without a single request having been refused.
# Production logged "authentication successful ... Upstream: CONNECTED" immediately
# followed by "stream startup failed: Market data access is not active" - our own message,
# for a connection that was never attempted.
# --------------------------------------------------------------------------- #
class _Session:
    def __init__(self, end_date: str):
        claims = json.dumps({"end_date": end_date, "user_name": "someone@example.com",
                             "role": "CUSTOMER", "list_package": "FiinQuant.Trial"})
        body = base64.urlsafe_b64encode(claims.encode()).decode().rstrip("=")
        self.access_token = f"eyJhbGciOiJIUzI1NiJ9.{body}.sig"


def test_an_expired_claim_alone_never_blocks_a_call():
    """The provider gets to say no. A date in a token does not."""
    access = FeedAccess()
    access.inspect_session(_Session("07/09/2020"))
    assert access.blocked("stream") is None
    assert access.blocked("history") is None


def test_the_claim_still_explains_a_real_rejection():
    access = FeedAccess()
    access.inspect_session(_Session("07/09/2020"))
    access.record("stream", "Service has expired.")
    message = access.wire(fresh=False, active=True, last_data_at=None)["message"]
    assert "2020-09-07" in message


def test_a_rejection_without_a_claim_still_reads_correctly():
    access = FeedAccess()
    access.record("stream", "Service has expired.")
    assert access.wire(fresh=False, active=True, last_data_at=None)["message"] == \
        MESSAGES["ENTITLEMENT_EXPIRED"]


def test_an_unexpired_claim_leaves_no_note_behind():
    access = FeedAccess()
    access.inspect_session(_Session("31/12/2099"))
    access.record("stream", "Service has expired.")
    assert access.wire(fresh=False, active=True, last_data_at=None)["message"] == \
        MESSAGES["ENTITLEMENT_EXPIRED"]


def test_a_malformed_token_is_ignored_rather_than_assumed_expired():
    access = FeedAccess()
    access.inspect_session(_Session("not-a-date"))
    access.inspect_session(object())
    assert access.blocked("stream") is None
