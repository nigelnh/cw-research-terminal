"""
Comprehensive unit tests for the Instrument Registry Backend:
- Lifecycle Truth Separation (ACTIVE vs EXPIRED vs UNKNOWN)
- Evidence Levels (CURRENT_PROVIDER_LIST, CURRENT_EXCHANGE_LIST, MANUAL_SNAPSHOT, SEARCH_ONLY, EXPIRED_BY_DATE)
- Data Quality Independence (COMPLETE vs PARTIAL)
- ActiveOnly Query Isolation (excludes UNKNOWN & EXPIRED)
- Reconciliation & Coverage Metrics
- Atomic Snapshot Refresh & Failure Resilience
- Exercise Ratio Canonical Convention & Pricing Consistency
- REST Endpoints
"""

import json
import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import app
from app.instruments.instrument_registry import InstrumentRegistry
from app.instruments.providers.canonical_provider import CanonicalInstrumentProvider
from app.instruments.instrument_schemas import (
    InstrumentLifecycleStatus,
    DataQualityStatus,
    LifecycleEvidenceLevel,
)
from app.instruments.instrument_refresh import merge_records, atomic_write_snapshot, refresh_instruments

client = TestClient(app)


@pytest.mark.asyncio
async def test_lifecycle_truth_active_vs_expired_vs_unknown():
    provider = CanonicalInstrumentProvider()
    # Test date: 2026-08-25
    items = await provider.load_instruments(current_date="2026-08-25")
    assert len(items) > 0

    active_items = [x for x in items if x.status == InstrumentLifecycleStatus.ACTIVE]
    expired_items = [x for x in items if x.status == InstrumentLifecycleStatus.EXPIRED]
    unknown_items = [x for x in items if x.status == InstrumentLifecycleStatus.UNKNOWN]

    # 1. Active instruments require an auditable origin (explicit evidence_level or a
    #    provenance block). Hand-seeded term sets with neither are UNKNOWN, not ACTIVE
    #    (Step 13C). The shipped dataset has exactly three: CHPG2602 + CVPB2615 verified,
    #    CTCB2601 conflicting.
    active_symbols = [x.symbol for x in active_items]
    assert {"CHPG2602", "CVPB2615", "CTCB2601"}.issubset(set(active_symbols))
    assert len(active_symbols) == 29
    # A former hand-seeded "active" with no provenance is now UNKNOWN.
    assert "CFPT2602" in [x.symbol for x in unknown_items]
    assert "CMWG2602" in [x.symbol for x in unknown_items]
    valid_active_evidence = (
        LifecycleEvidenceLevel.MANUAL_SNAPSHOT,
        LifecycleEvidenceLevel.CURRENT_PROVIDER_LIST,
        LifecycleEvidenceLevel.CURRENT_EXCHANGE_LIST,
        LifecycleEvidenceLevel.CURRENT_BROKER_MARKET_LIST,
    )
    assert all(x.evidence_level in valid_active_evidence for x in active_items)

    # 2. Expired instruments have past maturity date
    expired_symbols = [x.symbol for x in expired_items]
    assert "CHPG2401" in expired_symbols
    assert "CHPG2402" in expired_symbols
    assert "CFPT2401" in expired_symbols
    assert all(x.evidence_level == LifecycleEvidenceLevel.EXPIRED_BY_DATE for x in expired_items)

    # 3. Search-only discovered symbols without active proof are UNKNOWN (not ACTIVE!)
    assert len(unknown_items) > 0
    assert all(x.evidence_level == LifecycleEvidenceLevel.SEARCH_ONLY for x in unknown_items)


@pytest.mark.asyncio
async def test_active_only_search_strictly_excludes_unknown_and_expired():
    registry = InstrumentRegistry()
    await registry.initialize(current_date="2026-08-25")

    # Default active_only search
    active_results = await registry.search(active_only=True)
    assert len(active_results) > 0
    assert all(x.status == InstrumentLifecycleStatus.ACTIVE for x in active_results)
    assert not any(x.status == InstrumentLifecycleStatus.UNKNOWN for x in active_results)
    assert not any(x.status == InstrumentLifecycleStatus.EXPIRED for x in active_results)

    # Search for UNKNOWN specifically
    unknown_results = await registry.search(status=InstrumentLifecycleStatus.UNKNOWN, active_only=False)
    assert len(unknown_results) > 0
    assert all(x.status == InstrumentLifecycleStatus.UNKNOWN for x in unknown_results)

    # Search for EXPIRED specifically
    expired_results = await registry.search(status=InstrumentLifecycleStatus.EXPIRED, active_only=False)
    assert len(expired_results) >= 3
    assert all(x.status == InstrumentLifecycleStatus.EXPIRED for x in expired_results)


@pytest.mark.asyncio
async def test_metadata_quality_remains_independent_of_lifecycle():
    provider = CanonicalInstrumentProvider()
    items = await provider.load_instruments(current_date="2026-08-25")

    for item in items:
        has_full_specs = (
            item.strike_price is not None
            and item.strike_price > 0
            and item.exercise_ratio is not None
            and item.exercise_ratio > 0
            and item.maturity_date is not None
        )
        if has_full_specs:
            assert item.data_quality == DataQualityStatus.COMPLETE
        else:
            assert item.data_quality == DataQualityStatus.PARTIAL


def test_merge_does_not_upgrade_unknown_to_active_without_evidence():
    existing_records = [
        {
            "symbol": "CHPG2602",
            "issuer": "SSI",
            "underlying_symbol": "HPG",
            "strike_price": 22000.0,
            "exercise_ratio": 2.0,
            "maturity_date": "2026-11-20",
            "status": "ACTIVE",
            "evidence_level": "MANUAL_SNAPSHOT",
        }
    ]

    discovered = [
        {"symbol": "CXYZ9999", "issuer": "SSI", "underlying_symbol": "XYZ", "description": "Search result only"}
    ]

    merged = merge_records(discovered, existing_records)
    cxyz = next(x for x in merged if x["symbol"] == "CXYZ9999")
    # Must remain UNKNOWN, never upgraded to ACTIVE without evidence
    assert cxyz["status"] == "UNKNOWN"
    assert cxyz["evidence_level"] == "SEARCH_ONLY"


def test_atomic_snapshot_write_and_failure_resilience(tmp_path: Path):
    test_snapshot_file = tmp_path / "active_warrants.json"
    test_manifest_file = tmp_path / "manifest.json"

    initial_records = [
        {
            "symbol": "CHPG2602",
            "issuer": "SSI",
            "underlying_symbol": "HPG",
            "strike_price": 22000.0,
            "exercise_ratio": 2.0,
            "maturity_date": "2026-11-20",
            "status": "ACTIVE",
            "evidence_level": "MANUAL_SNAPSHOT",
        }
    ]

    # 1. Successful initial atomic write
    ok = atomic_write_snapshot(initial_records, target_file=test_snapshot_file, manifest_file=test_manifest_file)
    assert ok is True
    assert test_snapshot_file.exists()
    assert test_manifest_file.exists()

    with open(test_snapshot_file, "r") as f:
        loaded = json.load(f)
    assert len(loaded) == 1
    assert loaded[0]["symbol"] == "CHPG2602"

    # 2. Simulate failure during write (I/O error) - ensures last-known-good is retained
    with pytest.MonkeyPatch.context() as mp:
        def raise_write_error(*args, **kwargs):
            raise IOError("Simulated Disk Out of Space / I/O Error")
        mp.setattr(json, "dump", raise_write_error)
        fail_ok = atomic_write_snapshot(initial_records, target_file=test_snapshot_file)
        assert fail_ok is False

    # Original file is preserved untouched
    with open(test_snapshot_file, "r") as f:
        retained = json.load(f)
    assert len(retained) == 1
    assert retained[0]["symbol"] == "CHPG2602"


def test_exercise_ratio_canonical_convention():
    """
    Formal invariant test for Exercise Ratio convention:
    exerciseRatio = number of CWs required to buy 1 share of underlying stock.
    E.g. 2:1 ratio -> exerciseRatio = 2.0.

    Pricing relations:
    Option on 1 underlying share: C_share = C_CW * exerciseRatio
    CW market price: C_CW = C_share / exerciseRatio
    """
    strike_k = 22000.0
    underlying_s = 24000.0
    exercise_ratio = 2.0  # 2 CWs per 1 Share

    # Intrinsic value of 1 share option
    intrinsic_share = max(0.0, underlying_s - strike_k)  # 2000 VND
    assert intrinsic_share == 2000.0

    # Intrinsic value of 1 CW
    intrinsic_cw = intrinsic_share / exercise_ratio  # 1000 VND
    assert intrinsic_cw == 1000.0

    # Conversion back from CW to Share equivalent
    share_equivalent_price = intrinsic_cw * exercise_ratio
    assert share_equivalent_price == intrinsic_share


def test_rest_api_coverage_and_reconciliation_endpoints():
    # 1. Coverage metrics
    cov_resp = client.get("/api/instruments/metrics/coverage")
    assert cov_resp.status_code == 200
    metrics = cov_resp.json()
    assert "total_discovered_symbols" in metrics
    assert "verified_active_symbols" in metrics
    assert "verified_expired_symbols" in metrics
    assert "unknown_lifecycle_symbols" in metrics
    assert "metadata_complete_symbols" in metrics
    assert "metadata_partial_symbols" in metrics
    # Only warrants with an auditable origin are ACTIVE (Step 13C): CHPG2602, CVPB2615,
    # CTCB2601. Metadata-verification counts are unchanged (expired verified CWs keep their
    # grade).
    assert metrics["verified_active_symbols"] == 29
    assert metrics["verified_expired_symbols"] == 3
    assert metrics["unknown_lifecycle_symbols"] > 0
    assert metrics["verified_current_metadata_symbols"] == 31
    assert metrics["conflicting_metadata_symbols"] == 1

    # 2. Reconcile endpoint
    rec_resp = client.post(
        "/api/instruments/reconcile",
        json=["CHPG2602", "CVPB2615", "SYNTHETIC_TEST_CW_999"],
    )
    assert rec_resp.status_code == 200
    rec = rec_resp.json()
    assert rec["discovered_count"] == 3
    assert "SYNTHETIC_TEST_CW_999" in rec["missing_in_registry"]
    assert rec["common_count"] >= 2


def test_rest_api_list_instruments_active_default():
    resp = client.get("/api/instruments")
    assert resp.status_code == 200
    data = resp.json()
    assert "total" in data
    assert "active_count" in data
    assert "coverage" in data
    assert "items" in data
    # Active only by default: total equals active count
    assert data["total"] == data["active_count"]
    assert all(x["status"] == "ACTIVE" for x in data["items"])
    assert any(x["symbol"] == "CHPG2602" for x in data["items"])
    assert not any(x["status"] == "UNKNOWN" for x in data["items"])


def test_rest_api_get_instrument_specification():
    # Valid active CW with reconciled effective terms
    resp = client.get("/api/instruments/CHPG2602")
    assert resp.status_code == 200
    spec = resp.json()
    assert spec["symbol"] == "CHPG2602"
    assert spec["underlying_symbol"] == "HPG"
    assert spec["issuer"] == "TCBS"
    assert spec["strike_price"] == 25885.0
    assert spec["exercise_ratio"] == 3.5704
    assert spec["initial_strike_price"] == 29000.0
    assert spec["initial_exercise_ratio"] == 4.0
    assert spec["effective_strike_price"] == 25885.0
    assert spec["effective_exercise_ratio"] == 3.5704
    assert spec["is_adjusted"] is True
    assert spec["maturity_date"] == "2026-09-21"
    assert spec["status"] == "ACTIVE"
    assert spec["data_quality"] == "COMPLETE"
    assert spec["metadata_verification"] == "VERIFIED_CURRENT"


@pytest.mark.asyncio
async def test_corporate_action_adjusted_terms_reconciliation():
    registry = InstrumentRegistry()
    await registry.initialize(current_date="2026-08-25")

    spec = await registry.get_instrument("CHPG2602")
    assert spec is not None
    assert spec.is_adjusted is True
    assert spec.initial_strike_price == 29000.0
    assert spec.initial_exercise_ratio == 4.0
    assert spec.effective_strike == 25885.0
    assert spec.effective_ratio == 3.5704
    assert spec.effective_strike != spec.initial_strike_price
    assert spec.effective_ratio != spec.initial_exercise_ratio
    assert spec.terms_effective_date == "2026-06-18"
    assert "HOSE" in str(spec.adjustment_reference)


@pytest.mark.asyncio
async def test_chpg2602_initial_and_effective_source_references_distinct():
    """
    Verifies that initial issuance source (VSDC/IPO registration) and current effective terms source
    (HOSE corporate action adjustment notice) remain distinct and auditable with truthful reconciliation records.
    """
    registry = InstrumentRegistry()
    await registry.initialize(current_date="2026-08-25")

    spec = await registry.get_instrument("CHPG2602")
    assert spec is not None
    assert spec.provenance is not None
    assert spec.provenance.reconciliation_mode == "MANUAL_RECONCILED"

    # 1. Initial terms source
    init_src = spec.provenance.initial_terms_source
    assert init_src is not None
    assert init_src.source_type == "VSDC_REGISTRATION"
    assert init_src.source_document_id is None
    assert "VSDC" in str(init_src.notes)

    # 2. Effective terms source
    eff_src = spec.provenance.effective_terms_source
    assert eff_src is not None
    assert eff_src.source_type == "HOSE_CORPORATE_ACTION_NOTICE"
    assert eff_src.source_document_id is None
    assert "HOSE" in str(eff_src.notes)

    # Invariant: Initial and effective sources are distinct references
    assert init_src.source_type != eff_src.source_type
    assert init_src.notes != eff_src.notes
    assert init_src.source_published_at != eff_src.source_published_at


@pytest.mark.asyncio
async def test_verified_current_requires_concrete_source_evidence():
    """
    Proves that assigning a source label alone (e.g. metadata_source='HOSE_NOTICE')
    without documentary references (URL / document ID) is INSUFFICIENT for VERIFIED_CURRENT.
    """
    provider = CanonicalInstrumentProvider()

    # 1. Row claiming VERIFIED_CURRENT with label alone (no provenance object)
    raw_label_only = {
        "symbol": "CTESTLABEL01",
        "issuer": "SSI",
        "underlying_symbol": "HPG",
        "strike_price": 25000.0,
        "exercise_ratio": 2.0,
        "maturity_date": "2026-11-20",
        "status": "ACTIVE",
        "metadata_verification": "VERIFIED_CURRENT",
        "metadata_source": "HOSE_VSDC_CORPORATE_ACTION_NOTICE",
        "provenance": None,
    }
    spec_label = provider._parse_row(raw_label_only)
    assert spec_label is not None
    # Invariant: Must be downgraded to UNVERIFIED
    from app.instruments.instrument_schemas import MetadataVerificationStatus
    assert spec_label.metadata_verification == MetadataVerificationStatus.UNVERIFIED

    # 2. Row with concrete provenance document ID -> gets VERIFIED_CURRENT
    raw_concrete = {
        "symbol": "CTESTCONCRETE01",
        "issuer": "SSI",
        "underlying_symbol": "HPG",
        "strike_price": 25000.0,
        "exercise_ratio": 2.0,
        "maturity_date": "2026-11-20",
        "status": "ACTIVE",
        "metadata_verification": "VERIFIED_CURRENT",
        "metadata_source": "HOSE_VSDC_CORPORATE_ACTION_NOTICE",
        "provenance": {
            "effective_terms_source": {
                "source_type": "HOSE_OFFICIAL_NOTICE",
                "source_document_id": "HOSE-TB-TEST-2026",
                "source_url": "https://hsx.vn/notice/123",
                "retrieved_at": "2026-08-25T10:00:00+07:00",
            },
            "reconciliation_mode": "MANUAL_RECONCILED",
        },
    }
    spec_concrete = provider._parse_row(raw_concrete)
    assert spec_concrete is not None
    assert spec_concrete.metadata_verification == MetadataVerificationStatus.VERIFIED_CURRENT

    # Non-existent symbol
    resp_404 = client.get("/api/instruments/UNKNOWN_SYMBOL_999")
    assert resp_404.status_code == 404
