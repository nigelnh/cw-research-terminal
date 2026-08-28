"""Retry classification and bounded exponential backoff with jitter.

Reuses the provider's typed historical errors. No message-string sniffing and no
reinterpretation of hidden provider state: an open circuit is its own typed error
(:class:`HistoricalCircuitOpenError`) that carries the canonical reason it opened.
No infinite loops.
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass

from app.core.config import settings
from app.market_data.market_schemas import (
    HistoricalAuthError,
    HistoricalCircuitOpenError,
    HistoricalDataError,
    HistoricalEntitlementError,
    HistoricalRangeLimitError,
    HistoricalRateLimitError,
    HistoricalTransportError,
    HistoricalUpstreamError,
)

logger = logging.getLogger(__name__)

# Transient - safe to retry after backoff.
RETRYABLE: tuple[type[BaseException], ...] = (
    HistoricalTransportError,
    HistoricalUpstreamError,
    HistoricalRateLimitError,
)

# Permanent for this request - never retry, surface immediately.
NON_RETRYABLE: tuple[type[BaseException], ...] = (
    HistoricalRangeLimitError,
    HistoricalAuthError,
    HistoricalEntitlementError,
)


def is_retryable(exc: BaseException) -> bool:
    # An open circuit knows its own retryability (rate-limit / transient-upstream heal,
    # auth / entitlement do not).
    if isinstance(exc, HistoricalCircuitOpenError):
        return exc.is_retryable
    if isinstance(exc, NON_RETRYABLE):
        return False
    if isinstance(exc, RETRYABLE):
        return True
    # An unclassified error from deeper in the stack: treat as transport-transient once.
    return isinstance(exc, HistoricalDataError)


def classify(exc: BaseException) -> str:
    if isinstance(exc, HistoricalCircuitOpenError):
        return f"CIRCUIT_OPEN[{exc.reason}]"
    for name, cls in (
        ("RANGE_LIMIT", HistoricalRangeLimitError),
        ("AUTH", HistoricalAuthError),
        ("ENTITLEMENT", HistoricalEntitlementError),
        ("RATE_LIMIT", HistoricalRateLimitError),
        ("UPSTREAM", HistoricalUpstreamError),
        ("TRANSPORT", HistoricalTransportError),
    ):
        if isinstance(exc, cls):
            return name
    return "UNKNOWN"


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_retries: int
    base_seconds: float
    max_seconds: float

    @classmethod
    def from_settings(cls) -> "RetryPolicy":
        return cls(
            max_retries=int(settings.INGEST_MAX_RETRIES),
            base_seconds=float(settings.INGEST_RETRY_BASE_SECONDS),
            max_seconds=float(settings.INGEST_RETRY_MAX_SECONDS),
        )

    def backoff_seconds(self, attempt: int, *, rate_limited: bool = False) -> float:
        """Full-jitter exponential backoff. ``attempt`` is 1-based (first retry)."""
        raw = self.base_seconds * (2 ** max(0, attempt - 1))
        if rate_limited:
            raw *= 2.0
        capped = min(raw, self.max_seconds)
        return random.uniform(0.0, capped)


def _next_delay(policy: RetryPolicy, attempt: int, exc: BaseException) -> float:
    rate_limited = isinstance(exc, HistoricalRateLimitError) or (
        isinstance(exc, HistoricalCircuitOpenError) and exc.reason == "RATE_LIMIT"
    )
    delay = policy.backoff_seconds(attempt, rate_limited=rate_limited)
    if isinstance(exc, HistoricalCircuitOpenError):
        # Never retry before the circuit's own cooldown has elapsed.
        delay = max(delay, exc.retry_after_seconds + 1.0)
    return delay


async def call_with_retry(func, *, policy: RetryPolicy | None = None, label: str = "request", sleep=asyncio.sleep):
    """Await ``func()``; retry retryable ``HistoricalDataError``s with bounded backoff.

    Returns ``(result, attempts)``. Raises the last error when retries are exhausted or the
    error is non-retryable. ``sleep`` is injectable for deterministic tests.
    """
    pol = policy or RetryPolicy.from_settings()
    attempt = 0
    while True:
        try:
            result = await func()
            return result, attempt
        except BaseException as exc:  # noqa: BLE001 - we re-raise unless explicitly retryable
            if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt)):
                raise
            if not is_retryable(exc) or attempt >= pol.max_retries:
                raise
            attempt += 1
            delay = _next_delay(pol, attempt, exc)
            logger.warning(
                "%s: retryable %s (attempt %d/%d) - backing off %.1fs: %s",
                label, classify(exc), attempt, pol.max_retries, delay, exc,
            )
            await sleep(delay)
