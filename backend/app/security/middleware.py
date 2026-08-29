"""ASGI middleware: rate limiting, request-body size caps, API security headers.

All three are raw-ASGI (not ``BaseHTTPMiddleware``) so they do not buffer or break the
AI SSE stream, and they no-op cleanly for ``scope["type"] == "websocket"`` - the
websocket has its own limits in ``market_websocket``.
"""

from __future__ import annotations

import json
import logging

from starlette.datastructures import MutableHeaders
from starlette.requests import HTTPConnection
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import settings
from app.security.client_ip import resolve_client_key
from app.security.observability import security_counters
from app.security.policies import resolve_policy
from app.security.rate_limiter import rate_limiter

logger = logging.getLogger("cw-research-backend.security")

_JSON = [(b"content-type", b"application/json")]


async def _send_json(send: Send, status: int, body: dict, extra_headers: list | None = None) -> None:
    payload = json.dumps(body).encode()
    headers = list(_JSON) + [(b"content-length", str(len(payload)).encode())]
    if extra_headers:
        headers.extend(extra_headers)
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": payload})


def _peek_verified_subject(conn: HTTPConnection) -> str | None:
    """Best-effort: if a *valid* bearer token is present, return its subject. An invalid
    token yields None (the route still returns 401) - never rejects here."""
    auth = conn.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    token = auth[7:].strip()
    if not token:
        return None
    try:
        from app.auth.jwt_verifier import get_verifier

        claims = get_verifier().verify(token)
        sub = claims.get("sub")
        return str(sub) if sub else None
    except Exception:  # noqa: BLE001 - any failure -> anonymous keying
        return None


class RateLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not settings.PUBLIC_RATE_LIMIT_ENABLED:
            return await self.app(scope, receive, send)

        method = scope.get("method", "GET")
        if method == "OPTIONS":  # never rate-limit CORS preflight
            return await self.app(scope, receive, send)

        conn = HTTPConnection(scope)
        path = scope.get("path", "")
        policy = resolve_policy(method, path)
        if policy is None:
            return await self.app(scope, receive, send)

        subject = _peek_verified_subject(conn) if policy.key_scope == "subject_or_ip" else None
        key = resolve_client_key(conn, subject=subject)

        decision = await rate_limiter.check(
            tier=policy.tier, key=key, items=policy.items(), fail_closed=policy.fail_closed
        )
        if not decision.allowed:
            logger.info("rate limit: tier=%s retry_after=%ss%s", policy.tier, decision.retry_after,
                        " (degraded)" if decision.degraded else "")
            return await _send_json(
                send,
                429,
                {
                    "error": "rate_limited",
                    "detail": "Too many requests. Please slow down.",
                    "tier": policy.tier,
                },
                extra_headers=[(b"retry-after", str(decision.retry_after).encode())],
            )
        return await self.app(scope, receive, send)


class _BodyLimitExceeded(Exception):
    pass


class MaxBodySizeMiddleware:
    """413 for oversized request bodies. AI endpoints get a larger allowance than the
    small quant/watchlist/reconcile JSON payloads. WebSocket scope is untouched."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    def _limit_for(self, path: str) -> int:
        if path.startswith("/api/ai/"):
            return int(settings.AI_MAX_BODY_BYTES)
        return int(settings.API_MAX_BODY_BYTES)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        path = scope.get("path", "")
        limit = self._limit_for(path)

        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        content_length = headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > limit:
                    security_counters.incr("body_limit.rejected_total")
                    return await _send_json(
                        send, 413,
                        {"error": "payload_too_large", "detail": f"Request body exceeds {limit} bytes.", "limit_bytes": limit},
                    )
            except ValueError:
                pass  # malformed header -> fall through to the streaming guard

        received = 0
        response_started = False

        async def guarded_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise _BodyLimitExceeded()
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, guarded_receive, guarded_send)
        except _BodyLimitExceeded:
            security_counters.incr("body_limit.rejected_total")
            if not response_started:
                await _send_json(
                    send, 413,
                    {"error": "payload_too_large", "detail": f"Request body exceeds {limit} bytes.", "limit_bytes": limit},
                )
            else:
                logger.warning("body-limit exceeded after response started on %s; connection aborted", path)


class SecurityHeadersMiddleware:
    """Conservative headers appropriate for a JSON API (not a full CSP - that belongs to
    the eventual frontend host / reverse proxy)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not settings.SECURITY_HEADERS_ENABLED:
            return await self.app(scope, receive, send)

        path = scope.get("path", "")

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                h = MutableHeaders(scope=message)
                h.setdefault("x-content-type-options", "nosniff")
                h.setdefault("referrer-policy", "no-referrer")
                h.setdefault("x-frame-options", "DENY")
                h.setdefault("cross-origin-opener-policy", "same-origin")
                if path.startswith("/api/me/"):
                    h["cache-control"] = "no-store"
                if settings.SECURITY_HSTS_ENABLED:
                    h.setdefault("strict-transport-security", "max-age=31536000; includeSubDomains")
            await send(message)

        await self.app(scope, receive, send_wrapper)
