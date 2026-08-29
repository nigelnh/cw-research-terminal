"""Local JWT verification for Supabase access tokens.

Design goals
------------
* **No network call on the hot path.** HS256 is a pure local HMAC check. Asymmetric
  tokens verify against a JWKS key set that is fetched once and cached
  (``SUPABASE_JWKS_CACHE_SECONDS``); a normal protected request never hits Supabase.
* **Provider-agnostic surface.** Callers get a plain ``dict`` of claims and never see a
  ``jwt`` object. Swapping providers means rewriting only this file.
* **Fail closed, fail quiet.** Every failure is an :class:`AuthError` with a generic
  reason. Nothing about keys, secrets, or claim values is surfaced to the client.

Verified properties: cryptographic signature, ``exp`` (required), ``nbf``/``iat`` when
present (with configurable leeway), ``iss`` and ``aud`` when configured, and presence of
``sub``. The signing algorithm is taken from a small allow-list - ``alg: none`` and
unexpected algorithms are rejected outright.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from functools import lru_cache
from typing import TYPE_CHECKING, Any, Protocol

import jwt

if TYPE_CHECKING:
    from jwt.types import Options
from jwt import (
    DecodeError,
    ExpiredSignatureError,
    ImmatureSignatureError,
    InvalidAlgorithmError,
    InvalidAudienceError,
    InvalidIssuerError,
    InvalidSignatureError,
    InvalidTokenError,
    MissingRequiredClaimError,
)

from app.auth.errors import (
    AuthConfigError,
    AuthError,
    ClaimError,
    ExpiredTokenError,
    MalformedTokenError,
    SignatureError,
)
from app.core.config import settings

logger = logging.getLogger("cw-research-backend.auth")

_ASYMMETRIC_ALGS = ("RS256", "RS384", "RS512", "ES256", "ES384", "ES512", "PS256", "PS384", "PS512")
_HS_ALGS = ("HS256",)
_SUPPORTED_ALGS = _HS_ALGS + _ASYMMETRIC_ALGS


class _SigningKeyClient(Protocol):
    def get_signing_key_from_jwt(self, token: str) -> Any: ...


def _default_jwks_client_factory(url: str, cache_seconds: int) -> _SigningKeyClient:
    # PyJWKClient keeps the fetched JWK set in memory for ``lifespan`` seconds and only
    # refetches on a cache miss / expiry, so steady-state verification is offline. The
    # ``timeout`` bounds that rare refetch so a slow/hung JWKS host can never wedge a worker.
    return jwt.PyJWKClient(
        url,
        cache_keys=True,
        cache_jwk_set=True,
        lifespan=cache_seconds,
        timeout=max(1.0, float(settings.JWKS_FETCH_TIMEOUT_SECONDS)),
    )


class JwtVerifier:
    """Verifies one bearer token and returns its claims. Stateless apart from JWKS cache."""

    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        hs256_secrets: list[str],
        jwks_url: str,
        jwks_cache_seconds: int = 600,
        leeway: int = 30,
        jwks_client_factory: Callable[[str, int], _SigningKeyClient] | None = None,
    ) -> None:
        self._issuer = (issuer or "").strip()
        self._audience = (audience or "").strip()
        self._hs256_secrets = [s for s in hs256_secrets if s]
        self._jwks_url = (jwks_url or "").strip()
        self._jwks_cache_seconds = max(30, int(jwks_cache_seconds))
        self._leeway = max(0, int(leeway))
        self._jwks_client_factory = jwks_client_factory or _default_jwks_client_factory
        self._jwks_client: _SigningKeyClient | None = None

    @property
    def is_configured(self) -> bool:
        return bool(self._hs256_secrets or self._jwks_url)

    # -- internals ---------------------------------------------------------------

    def _decode_options(self) -> Options:
        return {
            "require": ["exp", "sub"],
            "verify_aud": bool(self._audience),
            "verify_iss": bool(self._issuer),
        }

    def _asymmetric_key(self, token: str) -> Any:
        if not self._jwks_url:
            raise AuthConfigError()
        if self._jwks_client is None:
            self._jwks_client = self._jwks_client_factory(self._jwks_url, self._jwks_cache_seconds)
        try:
            return self._jwks_client.get_signing_key_from_jwt(token).key
        except Exception as exc:  # PyJWKClientError, network errors, unknown kid
            logger.warning("JWKS signing-key resolution failed: %s", exc.__class__.__name__)
            raise SignatureError() from exc

    def _verify_hs256(self, token: str) -> dict[str, Any]:
        if not self._hs256_secrets:
            raise AuthConfigError()
        last_sig_error: Exception | None = None
        for secret in self._hs256_secrets:
            try:
                return jwt.decode(
                    token,
                    secret,
                    algorithms=list(_HS_ALGS),
                    audience=self._audience or None,
                    issuer=self._issuer or None,
                    leeway=self._leeway,
                    options=self._decode_options(),
                )
            except InvalidSignatureError as exc:
                last_sig_error = exc  # maybe another rotated secret matches
                continue
        raise SignatureError() from last_sig_error

    # -- public ----------------------------------------------------------------

    def verify(self, token: str) -> dict[str, Any]:
        if not token or token.count(".") != 2:
            raise MalformedTokenError()
        try:
            header = jwt.get_unverified_header(token)
        except Exception as exc:
            raise MalformedTokenError() from exc

        alg = str(header.get("alg", ""))
        if alg not in _SUPPORTED_ALGS:
            # includes "none" and anything unexpected
            raise ClaimError("unexpected_algorithm")

        try:
            if alg in _HS_ALGS:
                claims = self._verify_hs256(token)
            else:
                key = self._asymmetric_key(token)
                claims = jwt.decode(
                    token,
                    key,
                    algorithms=list(_ASYMMETRIC_ALGS),
                    audience=self._audience or None,
                    issuer=self._issuer or None,
                    leeway=self._leeway,
                    options=self._decode_options(),
                )
        except ExpiredSignatureError as exc:
            raise ExpiredTokenError() from exc
        except (
            InvalidAudienceError,
            InvalidIssuerError,
            ImmatureSignatureError,
            MissingRequiredClaimError,
        ) as exc:
            raise ClaimError() from exc
        except (InvalidSignatureError, InvalidAlgorithmError) as exc:
            raise SignatureError() from exc
        except DecodeError as exc:
            raise MalformedTokenError() from exc
        except AuthError:
            raise
        except InvalidTokenError as exc:
            raise AuthError() from exc

        sub = claims.get("sub")
        if not isinstance(sub, str) or not sub.strip():
            raise ClaimError("missing_sub")
        return claims


@lru_cache(maxsize=1)
def get_verifier() -> JwtVerifier:
    """Process-wide verifier built from ``settings``. Call ``get_verifier.cache_clear()``
    after mutating auth settings (tests do this)."""
    return JwtVerifier(
        issuer=settings.supabase_issuer(),
        audience=settings.SUPABASE_JWT_AUDIENCE,
        hs256_secrets=[settings.SUPABASE_JWT_SECRET, settings.auth_test_secret_active()],
        jwks_url=settings.supabase_jwks_url(),
        jwks_cache_seconds=settings.SUPABASE_JWKS_CACHE_SECONDS,
        leeway=settings.AUTH_JWT_LEEWAY_SECONDS,
    )
