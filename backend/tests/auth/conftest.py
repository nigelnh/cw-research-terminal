"""Deterministic auth fixtures - NO real Supabase project or network.

Tokens are minted in-process with PyJWT:
  * HS256 against a fixed test secret (exercises the shared-secret code path), and
  * RS256 against an in-test RSA keypair whose public JWK is served by a fake JWKS client
    (exercises the asymmetric / JWKS code path without any network).
"""

from __future__ import annotations

import time
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

TEST_ISSUER = "https://test-project.supabase.co/auth/v1"
TEST_AUDIENCE = "authenticated"
TEST_HS256_SECRET = "unit-test-hs256-secret-do-not-use-anywhere"
TEST_KID = "test-key-1"


def _now() -> int:
    return int(time.time())


def base_claims(**overrides: Any) -> dict[str, Any]:
    claims: dict[str, Any] = {
        "sub": "11111111-1111-1111-1111-111111111111",
        "email": "user-a@example.com",
        "aud": TEST_AUDIENCE,
        "iss": TEST_ISSUER,
        "role": "authenticated",
        "iat": _now() - 5,
        "exp": _now() + 3600,
    }
    claims.update(overrides)
    return claims


@pytest.fixture(scope="session")
def rsa_keypair() -> dict[str, Any]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    public_jwk.update({"kid": TEST_KID, "use": "sig", "alg": "RS256"})
    return {"private_key": private_key, "jwks": {"keys": [public_jwk]}}


@pytest.fixture(scope="session")
def fake_jwks_client_factory(rsa_keypair: dict[str, Any]):
    jwks = rsa_keypair["jwks"]

    class _FakeJWKSClient:
        """Mimics jwt.PyJWKClient.get_signing_key_from_jwt without any HTTP."""

        def __init__(self, url: str, cache_seconds: int) -> None:
            self.url = url

        def get_signing_key_from_jwt(self, token: str):
            kid = jwt.get_unverified_header(token).get("kid")
            for key in jwks["keys"]:
                if key["kid"] == kid:
                    return jwt.PyJWK.from_dict(key)
            raise jwt.exceptions.PyJWKClientError(f"no key for kid {kid!r}")

    return lambda url, cache_seconds: _FakeJWKSClient(url, cache_seconds)


@pytest.fixture
def make_hs256_token():
    def _make(claims: dict[str, Any] | None = None, *, secret: str = TEST_HS256_SECRET) -> str:
        return jwt.encode(claims or base_claims(), secret, algorithm="HS256")

    return _make


@pytest.fixture
def make_rs256_token(rsa_keypair: dict[str, Any]):
    def _make(claims: dict[str, Any] | None = None, *, kid: str | None = TEST_KID) -> str:
        headers = {"kid": kid} if kid else {}
        return jwt.encode(
            claims or base_claims(), rsa_keypair["private_key"], algorithm="RS256", headers=headers
        )

    return _make
