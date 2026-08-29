"""Research-universe model (Step 13C Workstream E).

No fabricated ACTIVE warrants; the registry is browsable via search; the default demo
universe is the curated verified set only.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.instruments.instrument_registry import instrument_registry
from app.instruments.instrument_schemas import (
    InstrumentLifecycleStatus,
    MetadataVerificationStatus,
)
from app.main import app

client = TestClient(app)


@pytest.mark.asyncio
async def test_only_provenanced_warrants_are_active():
    await instrument_registry.initialize(current_date="2026-08-29")
    active = await instrument_registry.search(active_only=True)
    assert {a.symbol for a in active} == {"CHPG2602", "CVPB2615", "CTCB2601"}
    verified = await instrument_registry.search(active_only=True, verified_only=True)
    assert {v.symbol for v in verified} == {"CHPG2602", "CVPB2615"}


@pytest.mark.asyncio
async def test_former_fabricated_warrant_is_unknown_with_no_terms():
    await instrument_registry.initialize(current_date="2026-08-29")
    spec = await instrument_registry.get_instrument("CFPT2601")
    assert spec is not None
    assert spec.status == InstrumentLifecycleStatus.UNKNOWN
    assert spec.metadata_verification == MetadataVerificationStatus.UNVERIFIED
    assert spec.effective_strike in (None, 0.0)  # fabricated strike removed


def test_search_discovers_registry_symbols_under_status_all():
    r = client.get("/api/instruments", params={"search": "CFPT", "status": "ALL"})
    assert r.status_code == 200
    syms = {i["symbol"] for i in r.json()["items"]}
    assert len(syms) > 20  # the whole CFPT family, not just the demo ones
    assert "CFPT2601" in syms


def test_active_default_returns_three():
    r = client.get("/api/instruments")
    assert r.status_code == 200
    data = r.json()
    assert data["active_count"] == 3
    assert data["total"] == 3


def test_default_universe_endpoint_is_curated_and_verified():
    r = client.get("/api/instruments/default-universe")
    assert r.status_code == 200
    items = r.json()["items"]
    syms = [i["symbol"] for i in items]
    assert "CTCB2601" not in syms  # the CONFLICTING warrant is not in the default demo
    cw_items = [i for i in items if i["instrument_type"] == "CW"]
    assert cw_items and all(i["metadata_verification"] == "VERIFIED_CURRENT" for i in cw_items)
    assert {"HPG", "VPB", "VNINDEX"}.issubset(set(syms))  # underlyings + index present


def test_unknown_symbol_rejected():
    r = client.get("/api/instruments/NOTREAL9")
    assert r.status_code == 404
