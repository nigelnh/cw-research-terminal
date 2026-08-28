"""Auth failure taxonomy.

Every verification failure is an :class:`AuthError` -> HTTP 401 with a generic ``reason``
that never leaks token internals. ``AuthConfigError`` is different: the deployment simply
has no auth configured, so protected routes answer 503 (not 401 - the caller did nothing
wrong).
"""

from __future__ import annotations


class AuthError(Exception):
    """A supplied credential was missing, malformed, or failed verification -> 401."""

    # Short, client-safe reason. NEVER include claim values, key ids, or token text.
    reason: str = "invalid_token"

    def __init__(self, reason: str | None = None) -> None:
        if reason:
            self.reason = reason
        super().__init__(self.reason)


class MissingTokenError(AuthError):
    reason = "missing_bearer_token"


class MalformedTokenError(AuthError):
    reason = "malformed_token"


class SignatureError(AuthError):
    reason = "invalid_signature"


class ExpiredTokenError(AuthError):
    reason = "token_expired"


class ClaimError(AuthError):
    """Wrong issuer / audience / not-yet-valid / missing required claim."""

    reason = "invalid_claims"


class AuthConfigError(Exception):
    """Auth is not configured on this deployment -> protected routes answer 503."""

    reason = "auth_not_configured"
