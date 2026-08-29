"""Public-API hardening (Step 10).

Bounds rate, request size, concurrency and cost on the anonymous public surface, and
makes deployment defaults safe (env-driven CORS / allowed hosts / security headers).
Nothing here puts the recruiter-demo product behind authentication.

Public surface:
    RateLimitMiddleware / MaxBodySizeMiddleware / SecurityHeadersMiddleware
    resolve_client_key            - trusted-proxy-aware client identity for limiting
    ai_call_gate / history_gapfill_gate - process-wide bounded concurrency
    security_counters             - sanitized counters for /health
"""

from app.security.client_ip import resolve_client_key
from app.security.concurrency import ai_call_gate, history_gapfill_gate
from app.security.middleware import (
    MaxBodySizeMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
)
from app.security.observability import security_counters

__all__ = [
    "MaxBodySizeMiddleware",
    "RateLimitMiddleware",
    "SecurityHeadersMiddleware",
    "ai_call_gate",
    "history_gapfill_gate",
    "resolve_client_key",
    "security_counters",
]
