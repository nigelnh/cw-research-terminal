"""The verified-identity dependency for protected routes.

``get_current_user`` is the ONLY thing routers should import. It:
  * pulls the bearer token from ``Authorization``,
  * verifies it locally (:mod:`app.auth.jwt_verifier`),
  * returns a small immutable :class:`CurrentUser` whose ``subject`` is the ownership key.

Failure mapping:
  * auth not configured on this deployment -> 503 ``auth_not_configured``
  * missing / malformed / expired / bad-signature / wrong-claims token -> 401
No token internals are ever returned to the client; diagnostics are logged without the raw JWT.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.errors import AuthConfigError, AuthError
from app.auth.jwt_verifier import get_verifier

logger = logging.getLogger("cw-research-backend.auth")

# auto_error=False: we raise our own 401 so the body/shape is consistent and generic.
_bearer_scheme = HTTPBearer(auto_error=False, description="Supabase access token")


@dataclass(frozen=True, slots=True)
class CurrentUser:
    """Verified caller identity. ``subject`` (JWT ``sub``) is the DB ownership key - it is
    immutable for the life of a Supabase user and is never taken from the request body."""

    subject: str
    email: str | None = None
    claims: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_claims(cls, claims: dict[str, Any]) -> CurrentUser:
        email = claims.get("email")
        return cls(
            subject=str(claims["sub"]).strip(),
            email=str(email).strip().lower() if isinstance(email, str) and email.strip() else None,
            claims=claims,
        )


def _unauthorized(reason: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"error": "unauthorized", "reason": reason},
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> CurrentUser:
    verifier = get_verifier()
    if not verifier.is_configured:
        # The caller did nothing wrong - this deployment just has no identity provider.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "auth_unavailable", "reason": "auth_not_configured"},
        )

    if credentials is None or (credentials.scheme or "").lower() != "bearer" or not credentials.credentials:
        raise _unauthorized("missing_bearer_token")

    try:
        claims = verifier.verify(credentials.credentials)
    except AuthConfigError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "auth_unavailable", "reason": "auth_not_configured"},
        )
    except AuthError as exc:
        # Generic 401. Log the class + reason only (SensitiveDataRedactor also strips JWTs).
        logger.info("auth rejected: %s (%s)", exc.reason, exc.__class__.__name__)
        raise _unauthorized(exc.reason)

    user = CurrentUser.from_claims(claims)
    # Stash for downstream logging / rate-limit keys without re-verifying.
    request.state.current_user = user
    return user


async def get_optional_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> CurrentUser | None:
    """Like ``get_current_user`` but never raises: returns ``None`` for a missing,
    malformed, or expired token instead of a 401/503. For routes where anonymous access
    is legitimate but a verified identity, when present, changes behaviour (e.g. the AI
    tier's guest-vs-signed-in quota)."""
    verifier = get_verifier()
    if not verifier.is_configured or credentials is None:
        return None
    if (credentials.scheme or "").lower() != "bearer" or not credentials.credentials:
        return None
    try:
        claims = verifier.verify(credentials.credentials)
    except (AuthConfigError, AuthError):
        return None
    user = CurrentUser.from_claims(claims)
    request.state.current_user = user
    return user
