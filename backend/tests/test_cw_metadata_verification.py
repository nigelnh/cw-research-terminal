"""CW contract-metadata verification model (Step 13A).

Covers: which verification grade unlocks the quant gate, the concrete-source requirement
for VERIFIED_CURRENT, and the automatic VERIFIED_CURRENT -> STALE age downgrade.
All deterministic - a synthetic single-row snapshot file, explicit `current_date`.
"""

from __future__ import annotations

import json

import pytest

from app.core.config import settings
from app.instruments.instrument_schemas import MetadataVerificationStatus, InstrumentLifecycleStatus
from app.instruments.providers.canonical_provider import CanonicalInstrumentProvider

pytestmark = pytest.mark.asyncio

_BASE = {
    "symbol": "CTEST2601",
    "issuer": "ACBS",
    "underlying_symbol": "VPB",
    "strike_price": 28500.0,
    "exercise_ratio": 2.0,
    "effective_strike_price": 28500.0,
    "effective_exercise_ratio": 2.0,
    "maturity_date": "2099-02-17",
    "last_trading_date": "2099-02-15",
    "listed_volume": 18000000,
    "issue_price": 2400.0,
    "instrument_type": "CW",
    "status": "ACTIVE",
    "evidence_level": "MANUAL_SNAPSHOT",
}

_CONCRETE_PROV = {
    "initial_terms_source": {
        "source_type": "PUBLIC_MARKET_DATA_AGGREGATOR",
        "source_url": "https://example.test/cw/CTEST2601",
        "retrieved_at": "2026-08-29T12:00:00+07:00",
        "notes": "reconciled from two public aggregators",
    },
    "effective_terms_source": None,
    "reconciliation_mode": "MANUAL_RECONCILED",
}


async def _load_one(tmp_path, row: dict, current_date: str):
    f = tmp_path / "one.json"
    f.write_text(json.dumps([row]), encoding="utf-8")
    p = CanonicalInstrumentProvider(data_file_path=f)
    await p.load_instruments(current_date=current_date)
    return await p.get_instrument(row["symbol"])


async def test_verified_current_with_concrete_source_unlocks(tmp_path):
    row = {**_BASE, "metadata_verification": "VERIFIED_CURRENT", "provenance": _CONCRETE_PROV,
           "metadata_retrieved_at": "2026-08-29T12:00:00+07:00"}
    spec = await _load_one(tmp_path, row, "2026-08-29")
    assert spec.metadata_verification == MetadataVerificationStatus.VERIFIED_CURRENT
    assert spec.status == InstrumentLifecycleStatus.ACTIVE


async def test_verified_current_label_without_concrete_source_is_unverified(tmp_path):
    row = {**_BASE, "metadata_verification": "VERIFIED_CURRENT", "provenance": None}
    spec = await _load_one(tmp_path, row, "2026-08-29")
    assert spec.metadata_verification == MetadataVerificationStatus.UNVERIFIED


async def test_conflicting_is_honoured_verbatim(tmp_path):
    row = {**_BASE, "metadata_verification": "CONFLICTING", "provenance": _CONCRETE_PROV}
    spec = await _load_one(tmp_path, row, "2026-08-29")
    assert spec.metadata_verification == MetadataVerificationStatus.CONFLICTING


async def test_stale_provenance_downgrades_verified_to_stale(tmp_path):
    # retrieved_at is fixed; evaluate at a date past the max-age window.
    row = {**_BASE, "metadata_verification": "VERIFIED_CURRENT", "provenance": _CONCRETE_PROV,
           "metadata_retrieved_at": "2026-08-29T12:00:00+07:00"}
    fresh = await _load_one(tmp_path, row, "2026-10-01")   # ~33 days -> fresh
    assert fresh.metadata_verification == MetadataVerificationStatus.VERIFIED_CURRENT
    stale_day = "2027-01-15"  # > INSTRUMENT_METADATA_MAX_AGE_DAYS (120) after 2026-08-29
    stale = await _load_one(tmp_path, row, stale_day)
    assert stale.metadata_verification == MetadataVerificationStatus.STALE


async def test_missing_provenance_timestamp_is_treated_as_stale(tmp_path):
    prov = json.loads(json.dumps(_CONCRETE_PROV))
    prov["initial_terms_source"].pop("retrieved_at", None)
    prov["initial_terms_source"]["source_document_id"] = "DOC-1"  # keep concrete-source true
    row = {**_BASE, "metadata_verification": "VERIFIED_CURRENT", "provenance": prov}
    row.pop("metadata_retrieved_at", None)
    # ProvenanceReference requires retrieved_at -> parsing the ref fails, so provenance is
    # dropped and the record falls back to UNVERIFIED (fail-closed).
    spec = await _load_one(tmp_path, row, "2026-08-29")
    assert spec.metadata_verification == MetadataVerificationStatus.UNVERIFIED


async def test_real_demo_symbols_end_state(tmp_path):
    """The two shipped demo CWs: CVPB2615 verified, CTCB2601 conflicting."""
    from app.instruments.providers.canonical_provider import CanonicalInstrumentProvider as P

    prov = P()
    await prov.load_instruments(current_date="2026-08-29")
    cvpb = await prov.get_instrument("CVPB2615")
    ctcb = await prov.get_instrument("CTCB2601")
    assert cvpb.metadata_verification == MetadataVerificationStatus.VERIFIED_CURRENT
    assert cvpb.status == InstrumentLifecycleStatus.ACTIVE and cvpb.effective_strike == 28500.0
    assert ctcb.metadata_verification == MetadataVerificationStatus.CONFLICTING
    assert ctcb.provenance is not None and ctcb.provenance.effective_terms_source is not None


async def test_conflicting_metadata_keeps_the_quant_gate_closed():
    """CONFLICTING must NOT unlock analytics even though data_quality is COMPLETE."""
    from app.instruments.instrument_registry import instrument_registry
    from app.quant.quant_engine import LiveQuantEngine
    from app.market_data.market_schemas import CanonicalQuote

    await instrument_registry.initialize()
    eng = LiveQuantEngine()
    und = CanonicalQuote(symbol="TCB", last_price=33400.0)
    cw = CanonicalQuote(symbol="CTCB2601", bid1_price=60.0, ask1_price=70.0)
    a = await eng.compute_warrant_analytics(
        "CTCB2601", spec=await instrument_registry.get_instrument("CTCB2601"), cw_state=cw, und_state=und
    )
    assert a.is_available is False
    assert "METADATA_NOT_VERIFIED_CURRENT" in a.unavailable_reason
    assert "CONFLICTING" in a.unavailable_reason
    assert a.iv_bid is None and a.greeks.delta is None
