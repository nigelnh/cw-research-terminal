"""AI failure taxonomy.

One machine code per failure class so production logs and the SSE/JSON error frame carry
a stable, greppable classification. The user-facing `message` stays short and never leaks
a provider payload, a key, a URL, or a stack trace.
"""

from __future__ import annotations

from enum import Enum

from fastapi import HTTPException

from app.ai.openrouter_client import (
    AiAuthenticationError,
    AiConfigurationError,
    AiModelUnavailableError,
    AiProviderError,
    AiRateLimitError,
    AiTimeoutError,
)
from app.security.concurrency import GateTimeout


class AiErrorCode(str, Enum):
    AI_DISABLED = "AI_DISABLED"                 # feature off / no API key on this server
    AI_BUDGET_EXCEEDED = "AI_BUDGET_EXCEEDED"   # process-local daily request budget hit
    RATE_LIMITED = "RATE_LIMITED"               # local limiter / concurrency gate (this server)
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"     # configured model 404/5xx at the provider
    UPSTREAM_AUTH_ERROR = "UPSTREAM_AUTH_ERROR" # provider 401/403 (bad/exhausted key)
    UPSTREAM_TIMEOUT = "UPSTREAM_TIMEOUT"       # provider did not respond in time
    UPSTREAM_RATE_LIMIT = "UPSTREAM_RATE_LIMIT" # provider 429
    UPSTREAM_ERROR = "UPSTREAM_ERROR"           # any other provider-side failure
    INVALID_REQUEST = "INVALID_REQUEST"         # request failed input validation
    STREAM_INTERRUPTED = "STREAM_INTERRUPTED"   # failure after streaming had begun
    NETWORK_ERROR = "NETWORK_ERROR"             # transport failure reaching the provider
    INTERNAL_ERROR = "INTERNAL_ERROR"           # unclassified


# Short, safe user-facing text per code.
_USER_MESSAGE: dict[AiErrorCode, str] = {
    AiErrorCode.AI_DISABLED: "The AI research assistant is turned off on this server.",
    AiErrorCode.AI_BUDGET_EXCEEDED: "The AI assistant has reached its daily usage limit. Try again tomorrow.",
    AiErrorCode.RATE_LIMITED: "The AI assistant is busy right now. Please retry in a moment.",
    AiErrorCode.MODEL_UNAVAILABLE: "The AI model is temporarily unavailable. Please try again shortly.",
    AiErrorCode.UPSTREAM_AUTH_ERROR: "The AI service is unavailable (provider authentication).",
    AiErrorCode.UPSTREAM_TIMEOUT: "The AI response timed out. Please try again.",
    AiErrorCode.UPSTREAM_RATE_LIMIT: "The AI provider is rate-limiting requests. Please retry in a moment.",
    AiErrorCode.UPSTREAM_ERROR: "The AI service returned an error. Please try again.",
    AiErrorCode.INVALID_REQUEST: "That request could not be processed.",
    AiErrorCode.STREAM_INTERRUPTED: "The AI response was interrupted. Please try again.",
    AiErrorCode.NETWORK_ERROR: "Could not reach the AI service. Please try again.",
    AiErrorCode.INTERNAL_ERROR: "An unexpected error occurred while generating the AI response.",
}

_HTTP_STATUS: dict[AiErrorCode, int] = {
    AiErrorCode.AI_DISABLED: 503,
    AiErrorCode.AI_BUDGET_EXCEEDED: 429,
    AiErrorCode.RATE_LIMITED: 503,
    AiErrorCode.MODEL_UNAVAILABLE: 503,
    AiErrorCode.UPSTREAM_AUTH_ERROR: 502,
    AiErrorCode.UPSTREAM_TIMEOUT: 504,
    AiErrorCode.UPSTREAM_RATE_LIMIT: 429,
    AiErrorCode.UPSTREAM_ERROR: 502,
    AiErrorCode.INVALID_REQUEST: 400,
    AiErrorCode.STREAM_INTERRUPTED: 500,
    AiErrorCode.NETWORK_ERROR: 502,
    AiErrorCode.INTERNAL_ERROR: 500,
}


def classify(exc: BaseException, *, stream_started: bool = False) -> AiErrorCode:
    """Map an exception to a code. `stream_started` upgrades a post-first-token failure to
    STREAM_INTERRUPTED so logs distinguish 'never connected' from 'dropped mid-answer'."""
    if isinstance(exc, GateTimeout):
        return AiErrorCode.RATE_LIMITED
    if isinstance(exc, AiConfigurationError):
        return AiErrorCode.AI_DISABLED
    if isinstance(exc, AiAuthenticationError):
        return AiErrorCode.UPSTREAM_AUTH_ERROR
    if isinstance(exc, AiRateLimitError):
        return AiErrorCode.UPSTREAM_RATE_LIMIT
    if isinstance(exc, AiModelUnavailableError):
        return AiErrorCode.MODEL_UNAVAILABLE
    if isinstance(exc, AiTimeoutError):
        return AiErrorCode.STREAM_INTERRUPTED if stream_started else AiErrorCode.UPSTREAM_TIMEOUT
    if isinstance(exc, AiProviderError):
        msg = (getattr(exc, "message", "") or "").lower()
        if "connect" in msg or "network" in msg or "interrupt" in msg:
            return AiErrorCode.STREAM_INTERRUPTED if stream_started else AiErrorCode.NETWORK_ERROR
        return AiErrorCode.STREAM_INTERRUPTED if stream_started else AiErrorCode.UPSTREAM_ERROR
    if isinstance(exc, HTTPException):
        sc = exc.status_code
        if sc == 429:
            return AiErrorCode.AI_BUDGET_EXCEEDED
        if sc in (400, 413, 422):
            return AiErrorCode.INVALID_REQUEST
        if sc == 503:
            return AiErrorCode.AI_DISABLED
        return AiErrorCode.INTERNAL_ERROR
    return AiErrorCode.STREAM_INTERRUPTED if stream_started else AiErrorCode.INTERNAL_ERROR


def user_message(code: AiErrorCode) -> str:
    return _USER_MESSAGE.get(code, _USER_MESSAGE[AiErrorCode.INTERNAL_ERROR])


def http_status(code: AiErrorCode) -> int:
    return _HTTP_STATUS.get(code, 500)
