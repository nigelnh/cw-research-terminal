"""A retired model slug is a configuration fault, not an outage.

The provider returns 404 for a slug it does not know. That was folded in with 502/503/504,
so the user saw "The AI model is temporarily unavailable. Please try again shortly." for a
model that had been retired and was never coming back - advice that could not work, and
which gave no hint that the fix was a server setting. This pins the two apart.
"""
import pytest

from app.ai.ai_errors import AiErrorCode, classify, http_status, user_message
from app.ai.openrouter_client import AiModelNotFoundError, AiModelUnavailableError


def test_a_retired_slug_is_classified_apart_from_an_outage():
    assert classify(AiModelNotFoundError("minimax/minimax-m3:free")) is AiErrorCode.MODEL_NOT_FOUND
    assert classify(AiModelUnavailableError()) is AiErrorCode.MODEL_UNAVAILABLE


def test_the_message_names_the_model_so_the_failure_is_actionable():
    exc = AiModelNotFoundError("minimax/minimax-m3:free")
    msg = user_message(AiErrorCode.MODEL_NOT_FOUND, exc)
    assert "minimax/minimax-m3:free" in msg
    assert "OPENROUTER_MODEL" in msg


def test_it_never_tells_the_user_to_retry_something_that_cannot_succeed():
    exc = AiModelNotFoundError("dead/model:free")
    msg = user_message(AiErrorCode.MODEL_NOT_FOUND, exc).lower()
    assert "try again" not in msg
    # ...while a genuine outage still should say exactly that
    assert "try again" in user_message(AiErrorCode.MODEL_UNAVAILABLE).lower()


def test_without_the_exception_it_still_says_configuration_not_outage():
    msg = user_message(AiErrorCode.MODEL_NOT_FOUND).lower()
    assert "configuration" in msg
    assert "try again" not in msg


def test_it_leaks_no_key_url_or_payload():
    msg = user_message(AiErrorCode.MODEL_NOT_FOUND, AiModelNotFoundError("x/y:free"))
    for forbidden in ("sk-or-", "http://", "https://", "Traceback"):
        assert forbidden not in msg


def test_the_status_stays_503():
    assert http_status(AiErrorCode.MODEL_NOT_FOUND) == 503


@pytest.mark.parametrize("code", list(AiErrorCode))
def test_every_code_still_has_a_message_and_a_status(code):
    assert user_message(code)
    assert 400 <= http_status(code) < 600
