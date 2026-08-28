"""Authentication boundary.

The backend does NOT issue sessions, store passwords, or run OAuth. It only *verifies*
the access token that the identity provider (Supabase Auth) minted, and derives a small
immutable :class:`CurrentUser` from the verified claims. Nothing outside this package
should import a provider SDK or touch a raw JWT.

Public surface:
    get_current_user  - FastAPI dependency; 401 on any auth failure, 503 when auth is
                        not configured on this deployment.
    CurrentUser       - typed identity (subject, email, claims).
    AuthError         - base class for verification failures (mapped to 401 by the dep).
"""

from app.auth.current_user import CurrentUser, get_current_user
from app.auth.errors import AuthConfigError, AuthError

__all__ = ["AuthConfigError", "AuthError", "CurrentUser", "get_current_user"]
