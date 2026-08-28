"""End-to-end /api/me/watchlist: real HS256 verification -> real repository -> real PostgreSQL.

No Supabase network. Tokens are minted in-process against a test secret and the backend
verifies them through the exact production code path (app.auth.jwt_verifier). Covers auth
failure semantics, ownership isolation between two users, forged-owner payloads, ordering,
capacity, duplicates, and transactional behavior.
"""

from __future__ import annotations

import time

import jwt
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.auth.jwt_verifier import get_verifier
from app.core.config import settings
from app.main import app
from app.persistence import database as pdb

pytestmark = pytest.mark.asyncio

_ISSUER = "https://test-project.supabase.co/auth/v1"
_AUD = "authenticated"
_SECRET = "me-watchlist-api-test-hs256-secret-32bytes+"

SUBJECT_A = "aaaaaaaa-1111-1111-1111-111111111111"
SUBJECT_B = "bbbbbbbb-2222-2222-2222-222222222222"


def _token(*, sub: str, email: str = "x@example.com", **overrides) -> str:
    secret = overrides.pop("_secret", _SECRET)
    now = int(time.time())
    claims = {
        "sub": sub,
        "email": email,
        "aud": _AUD,
        "iss": _ISSUER,
        "role": "authenticated",
        "iat": now - 5,
        "exp": now + 3600,
    }
    claims.update(overrides)
    return jwt.encode(claims, secret, algorithm="HS256")


@pytest_asyncio.fixture
async def api(engine):
    prev_engine, prev_sm = pdb._engine, pdb._sessionmaker
    pdb.configure(engine)

    saved = {
        k: getattr(settings, k)
        for k in ("SUPABASE_JWT_SECRET", "SUPABASE_JWT_ISSUER", "SUPABASE_JWT_AUDIENCE", "SUPABASE_URL", "ENVIRONMENT")
    }
    settings.SUPABASE_JWT_SECRET = _SECRET
    settings.SUPABASE_JWT_ISSUER = _ISSUER
    settings.SUPABASE_JWT_AUDIENCE = _AUD
    settings.SUPABASE_URL = ""
    settings.ENVIRONMENT = "development"
    get_verifier.cache_clear()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    for k, v in saved.items():
        setattr(settings, k, v)
    get_verifier.cache_clear()
    pdb._engine, pdb._sessionmaker = prev_engine, prev_sm


def _auth(sub: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(sub=sub)}"}


# --- auth failure semantics (Section 19) -----------------------------------

async def test_no_token_is_401(api):
    r = await api.get("/api/me/watchlist")
    assert r.status_code == 401
    assert r.json()["detail"]["reason"] == "missing_bearer_token"


async def test_malformed_token_is_401(api):
    r = await api.get("/api/me/watchlist", headers={"Authorization": "Bearer not.a.jwt"})
    assert r.status_code == 401


async def test_expired_token_is_401(api):
    tok = _token(sub=SUBJECT_A, exp=int(time.time()) - 3600, iat=int(time.time()) - 7200)
    r = await api.get("/api/me/watchlist", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 401
    assert r.json()["detail"]["reason"] == "token_expired"


async def test_bad_signature_is_401(api):
    tok = _token(sub=SUBJECT_A, _secret="a-totally-different-secret-of-32-bytes+++")
    r = await api.get("/api/me/watchlist", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 401
    assert r.json()["detail"]["reason"] == "invalid_signature"


async def test_wrong_issuer_is_401(api):
    tok = _token(sub=SUBJECT_A, iss="https://evil.example.com/auth/v1")
    r = await api.get("/api/me/watchlist", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 401


async def test_wrong_audience_is_401(api):
    tok = _token(sub=SUBJECT_A, aud="not-authenticated")
    r = await api.get("/api/me/watchlist", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 401


async def test_no_generic_500_on_auth_failure(api):
    for h in ({}, {"Authorization": "Bearer x"}, {"Authorization": "Basic abc"}):
        r = await api.get("/api/me/watchlist", headers=h)
        assert r.status_code in (401, 403)


# --- happy path + ownership isolation (Section 20) -------------------------

async def test_empty_before_first_save(api):
    r = await api.get("/api/me/watchlist", headers=_auth(SUBJECT_A))
    assert r.status_code == 200
    assert r.json() == {"items": [], "updatedAt": None, "source": "server"}


async def test_put_then_get_round_trips_with_order_and_canonical_metadata(api):
    # Client sends only symbols (+ a deliberately wrong strike on the CW).
    body = {
        "items": [
            {"symbol": "HPG"},
            {"symbol": "CTCB2601", "strikePrice": 1, "issuer": "EVIL", "instrumentType": "STOCK"},
            {"symbol": "VHM"},
        ]
    }
    r = await api.put("/api/me/watchlist", json=body, headers=_auth(SUBJECT_A))
    assert r.status_code == 200
    assert [i["symbol"] for i in r.json()["items"]] == ["HPG", "CTCB2601", "VHM"]

    r2 = await api.get("/api/me/watchlist", headers=_auth(SUBJECT_A))
    items = r2.json()["items"]
    assert [i["symbol"] for i in items] == ["HPG", "CTCB2601", "VHM"]
    assert items[0]["instrumentType"] == "STOCK"
    # canonical registry facts win over the forged client values
    assert items[1]["instrumentType"] == "CW"
    assert items[1]["underlyingSymbol"] == "TCB"
    assert items[1]["issuer"] == "KIS"
    assert items[1]["strikePrice"] == 25000.0
    assert items[1]["exerciseRatio"] == 2.0
    assert r2.json()["updatedAt"] is not None


async def test_two_users_never_see_each_others_watchlist(api):
    await api.put(
        "/api/me/watchlist",
        json={"items": [{"symbol": "HPG"}, {"symbol": "VHM"}]},
        headers=_auth(SUBJECT_A),
    )
    await api.put(
        "/api/me/watchlist",
        json={"items": [{"symbol": "FPT"}, {"symbol": "MWG"}]},
        headers=_auth(SUBJECT_B),
    )
    a = await api.get("/api/me/watchlist", headers=_auth(SUBJECT_A))
    b = await api.get("/api/me/watchlist", headers=_auth(SUBJECT_B))
    assert {i["symbol"] for i in a.json()["items"]} == {"HPG", "VHM"}
    assert {i["symbol"] for i in b.json()["items"]} == {"FPT", "MWG"}


async def test_forged_owner_id_in_body_is_ignored(api):
    await api.put(
        "/api/me/watchlist", json={"items": [{"symbol": "HPG"}]}, headers=_auth(SUBJECT_A)
    )
    # User B sends a payload that tries to target A via every plausible field name.
    r = await api.put(
        "/api/me/watchlist",
        json={
            "owner_id": SUBJECT_A,
            "ownerSubject": SUBJECT_A,
            "user_id": SUBJECT_A,
            "sub": SUBJECT_A,
            "items": [{"symbol": "MWG"}],
        },
        headers=_auth(SUBJECT_B),
    )
    assert r.status_code == 200
    a = await api.get("/api/me/watchlist", headers=_auth(SUBJECT_A))
    b = await api.get("/api/me/watchlist", headers=_auth(SUBJECT_B))
    assert [i["symbol"] for i in a.json()["items"]] == ["HPG"]
    assert [i["symbol"] for i in b.json()["items"]] == ["MWG"]


# --- instrument metadata integrity (data-integrity correction) -----------

async def test_forged_strike_issuer_ratio_cannot_be_persisted(api):
    r = await api.put(
        "/api/me/watchlist",
        json={
            "items": [
                {
                    "symbol": "CTCB2601",
                    "instrumentType": "STOCK",
                    "underlyingSymbol": "HACKED",
                    "issuer": "EVIL CORP",
                    "strikePrice": 999999,
                    "exerciseRatio": 123.4,
                    "maturityDate": "2099-01-01",
                    "lastTradingDate": "2099-01-01",
                }
            ]
        },
        headers=_auth(SUBJECT_A),
    )
    assert r.status_code == 200
    item = (await api.get("/api/me/watchlist", headers=_auth(SUBJECT_A))).json()["items"][0]
    assert item["instrumentType"] == "CW"
    assert item["underlyingSymbol"] == "TCB"
    assert item["issuer"] == "KIS"
    assert item["strikePrice"] == 25000.0
    assert item["exerciseRatio"] == 2.0
    assert item["maturityDate"] == "2026-12-10"
    assert item["lastTradingDate"] == "2026-12-08"


async def test_unknown_symbol_is_rejected(api):
    r = await api.put(
        "/api/me/watchlist",
        json={"items": [{"symbol": "HPG"}, {"symbol": "ZZZ9NOPE"}]},
        headers=_auth(SUBJECT_A),
    )
    assert r.status_code == 400
    assert "unknown instrument" in r.json()["detail"]["reason"]
    # nothing persisted
    assert (await api.get("/api/me/watchlist", headers=_auth(SUBJECT_A))).json()["items"] == []


async def test_partial_but_known_registry_cw_is_accepted(api):
    # CVPB2615 exists in the registry but has no strike/ratio/maturity (data_quality PARTIAL).
    r = await api.put(
        "/api/me/watchlist", json={"items": [{"symbol": "CVPB2615"}]}, headers=_auth(SUBJECT_A)
    )
    assert r.status_code == 200
    item = (await api.get("/api/me/watchlist", headers=_auth(SUBJECT_A))).json()["items"][0]
    assert item["instrumentType"] == "CW"
    assert item["issuer"] == "ACBS"
    assert item["underlyingSymbol"] == "VPB"
    assert item["strikePrice"] is None
    assert item["exerciseRatio"] is None


async def test_recognized_equity_not_a_cw_underlying_is_accepted(api):
    # NVL is a HOSE blue chip on the curated equity allow-list but not a CW underlying.
    r = await api.put(
        "/api/me/watchlist",
        json={"items": [{"symbol": "NVL"}, {"symbol": "HPG"}]},
        headers=_auth(SUBJECT_A),
    )
    assert r.status_code == 200
    types = {i["symbol"]: i["instrumentType"] for i in (await api.get("/api/me/watchlist", headers=_auth(SUBJECT_A))).json()["items"]}
    assert types == {"NVL": "STOCK", "HPG": "STOCK"}


async def test_notes_are_the_only_user_authored_field_and_are_preserved(api):
    r = await api.put(
        "/api/me/watchlist",
        json={"items": [{"symbol": "HPG", "notes": "watching the breakout"}]},
        headers=_auth(SUBJECT_A),
    )
    assert r.status_code == 200
    item = (await api.get("/api/me/watchlist", headers=_auth(SUBJECT_A))).json()["items"][0]
    assert item["notes"] == "watching the breakout"


# --- validation (Section 8) ----------------------------------------------

async def test_duplicate_symbols_rejected_400(api):
    r = await api.put(
        "/api/me/watchlist",
        json={"items": [{"symbol": "HPG"}, {"symbol": "hpg"}]},
        headers=_auth(SUBJECT_A),
    )
    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "invalid_watchlist"


async def test_over_capacity_rejected_400(api):
    items = [{"symbol": f"SYM{i:03d}"} for i in range(settings.ME_WATCHLIST_MAX_ITEMS + 1)]
    r = await api.put("/api/me/watchlist", json={"items": items}, headers=_auth(SUBJECT_A))
    assert r.status_code == 400
    assert "maximum" in r.json()["detail"]["reason"]


async def test_invalid_replace_does_not_destroy_existing_list(api):
    await api.put(
        "/api/me/watchlist",
        json={"items": [{"symbol": "HPG"}, {"symbol": "VHM"}]},
        headers=_auth(SUBJECT_A),
    )
    bad = await api.put(
        "/api/me/watchlist",
        json={"items": [{"symbol": "SSI"}, {"symbol": "SSI"}]},
        headers=_auth(SUBJECT_A),
    )
    assert bad.status_code == 400
    still = await api.get("/api/me/watchlist", headers=_auth(SUBJECT_A))
    assert [i["symbol"] for i in still.json()["items"]] == ["HPG", "VHM"]
