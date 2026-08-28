"""Unit tests for JwtVerifier: signature, exp, nbf, iss, aud, alg allow-list, malformed."""

from __future__ import annotations

import time

import jwt
import pytest

from app.auth.errors import (
    ClaimError,
    ExpiredTokenError,
    MalformedTokenError,
    SignatureError,
)
from app.auth.jwt_verifier import JwtVerifier
from tests.auth.conftest import (
    TEST_AUDIENCE,
    TEST_HS256_SECRET,
    TEST_ISSUER,
    base_claims,
)


@pytest.fixture
def verifier(fake_jwks_client_factory) -> JwtVerifier:
    return JwtVerifier(
        issuer=TEST_ISSUER,
        audience=TEST_AUDIENCE,
        hs256_secrets=[TEST_HS256_SECRET],
        jwks_url="https://test-project.supabase.co/auth/v1/.well-known/jwks.json",
        jwks_cache_seconds=600,
        leeway=30,
        jwks_client_factory=fake_jwks_client_factory,
    )


# --- happy paths ------------------------------------------------------------

def test_valid_hs256_token_returns_claims(verifier, make_hs256_token):
    claims = verifier.verify(make_hs256_token())
    assert claims["sub"] == "11111111-1111-1111-1111-111111111111"
    assert claims["email"] == "user-a@example.com"


def test_valid_rs256_token_via_jwks(verifier, make_rs256_token):
    claims = verifier.verify(make_rs256_token())
    assert claims["sub"] == "11111111-1111-1111-1111-111111111111"


def test_nbf_in_the_past_is_accepted(verifier, make_hs256_token):
    claims = verifier.verify(make_hs256_token(base_claims(nbf=int(time.time()) - 60)))
    assert claims["sub"]


# --- rejections ------------------------------------------------------------

def test_expired_token_rejected(verifier, make_hs256_token):
    token = make_hs256_token(base_claims(exp=int(time.time()) - 3600, iat=int(time.time()) - 7200))
    with pytest.raises(ExpiredTokenError):
        verifier.verify(token)


def test_not_yet_valid_token_rejected(verifier, make_hs256_token):
    token = make_hs256_token(base_claims(nbf=int(time.time()) + 3600))
    with pytest.raises(ClaimError):
        verifier.verify(token)


def test_wrong_signature_rejected(verifier, make_hs256_token):
    token = make_hs256_token(secret="a-completely-different-secret-value-32b+")
    with pytest.raises(SignatureError):
        verifier.verify(token)


def test_rs256_wrong_key_rejected(verifier):
    from cryptography.hazmat.primitives.asymmetric import rsa

    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = jwt.encode(base_claims(), other, algorithm="RS256", headers={"kid": "test-key-1"})
    with pytest.raises(SignatureError):
        verifier.verify(token)


def test_wrong_issuer_rejected(verifier, make_hs256_token):
    token = make_hs256_token(base_claims(iss="https://evil.example.com/auth/v1"))
    with pytest.raises(ClaimError):
        verifier.verify(token)


def test_wrong_audience_rejected(verifier, make_hs256_token):
    token = make_hs256_token(base_claims(aud="some-other-audience"))
    with pytest.raises(ClaimError):
        verifier.verify(token)


def test_missing_sub_rejected(verifier, make_hs256_token):
    claims = base_claims()
    del claims["sub"]
    with pytest.raises(ClaimError):
        verifier.verify(make_hs256_token(claims))


def test_alg_none_rejected(verifier):
    token = jwt.encode(base_claims(), key=None, algorithm="none")
    with pytest.raises(ClaimError):
        verifier.verify(token)


def test_malformed_token_rejected(verifier):
    for bad in ("", "not-a-jwt", "a.b", "a.b.c.d", "header.payload."):
        with pytest.raises((MalformedTokenError, SignatureError)):
            verifier.verify(bad)


def test_hs256_rotation_second_secret_matches(fake_jwks_client_factory, make_hs256_token):
    v = JwtVerifier(
        issuer=TEST_ISSUER,
        audience=TEST_AUDIENCE,
        hs256_secrets=["stale-old-secret-rotated-out-but-32-bytes", TEST_HS256_SECRET],
        jwks_url="",
        jwks_client_factory=fake_jwks_client_factory,
    )
    assert v.verify(make_hs256_token())["sub"]
