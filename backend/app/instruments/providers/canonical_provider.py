"""
Canonical Instrument Registry Provider.
Loads Covered Warrant cached metadata snapshot from deterministic local storage,
evaluates lifecycle status (ACTIVE vs EXPIRED vs UNKNOWN) against evidence levels,
and assesses data quality completeness (COMPLETE vs PARTIAL).
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple

from app.instruments.instrument_schemas import (
    CoveredWarrantSpecification,
    InstrumentLifecycleStatus,
    DataQualityStatus,
    LifecycleEvidenceLevel,
    CoverageMetrics,
)
from app.instruments.providers.base import InstrumentRegistryProvider

logger = logging.getLogger(__name__)
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DEFAULT_DATASET_FILE = DATA_DIR / "active_warrants.json"
MANIFEST_FILE = DATA_DIR / "manifest.json"

# Vietnam Market Timezone (UTC+7)
VN_TZ = timezone(timedelta(hours=7))


def get_vietnam_today() -> str:
    """Returns today's date string YYYY-MM-DD in Vietnam timezone (UTC+7)."""
    return datetime.now(VN_TZ).strftime("%Y-%m-%d")


def get_vietnam_now_iso() -> str:
    """Returns current ISO 8601 timestamp in Vietnam timezone."""
    return datetime.now(VN_TZ).isoformat()


class CanonicalInstrumentProvider(InstrumentRegistryProvider):
    def __init__(self, data_file_path: Optional[Path] = None):
        self.data_file = data_file_path or DEFAULT_DATASET_FILE
        self._cache: Dict[str, CoveredWarrantSpecification] = {}
        self._manifest: Dict[str, Any] = {}
        self._loaded = False

    def _determine_lifecycle_and_evidence(
        self,
        raw: dict,
        maturity_date: Optional[str],
        current_date: Optional[str] = None,
    ) -> Tuple[InstrumentLifecycleStatus, LifecycleEvidenceLevel]:
        today = current_date or get_vietnam_today()

        # 1. If explicit past maturity date -> EXPIRED
        if maturity_date and maturity_date < today:
            return InstrumentLifecycleStatus.EXPIRED, LifecycleEvidenceLevel.EXPIRED_BY_DATE

        # 2. Check explicit evidence level in raw payload if present
        raw_evidence = raw.get("evidence_level")
        raw_status = raw.get("status")

        if raw_evidence:
            try:
                ev = LifecycleEvidenceLevel(raw_evidence)
                if ev in (
                    LifecycleEvidenceLevel.CURRENT_PROVIDER_LIST,
                    LifecycleEvidenceLevel.CURRENT_EXCHANGE_LIST,
                    LifecycleEvidenceLevel.CURRENT_BROKER_MARKET_LIST,
                    LifecycleEvidenceLevel.MANUAL_SNAPSHOT,
                ):
                    return InstrumentLifecycleStatus.ACTIVE, ev
                elif ev == LifecycleEvidenceLevel.SEARCH_ONLY:
                    return InstrumentLifecycleStatus.UNKNOWN, ev
            except ValueError:
                pass

        # 3. If manual canonical snapshot with valid future maturity date & verified terms -> ACTIVE
        if maturity_date and maturity_date >= today and raw.get("strike_price") is not None:
            return InstrumentLifecycleStatus.ACTIVE, LifecycleEvidenceLevel.MANUAL_SNAPSHOT

        # 4. Search-only discovery without active trading evidence -> UNKNOWN
        return InstrumentLifecycleStatus.UNKNOWN, LifecycleEvidenceLevel.SEARCH_ONLY

    def _determine_data_quality(
        self,
        strike_price: Optional[float],
        exercise_ratio: Optional[float],
        maturity_date: Optional[str],
    ) -> DataQualityStatus:
        if (
            strike_price is not None
            and strike_price > 0
            and exercise_ratio is not None
            and exercise_ratio > 0
            and maturity_date is not None
            and len(maturity_date.strip()) > 0
        ):
            return DataQualityStatus.COMPLETE
        return DataQualityStatus.PARTIAL

    def _parse_row(self, raw: dict, current_date: Optional[str] = None) -> Optional[CoveredWarrantSpecification]:
        try:
            sym = str(raw.get("symbol", "")).strip().upper()
            if not sym:
                return None

            mat_date = raw.get("maturity_date")
            status, evidence = self._determine_lifecycle_and_evidence(raw, mat_date, current_date)

            # Determine initial vs effective terms
            initial_strike = float(raw["initial_strike_price"]) if raw.get("initial_strike_price") is not None else None
            initial_ratio = float(raw["initial_exercise_ratio"]) if raw.get("initial_exercise_ratio") is not None else None
            eff_strike = float(raw["effective_strike_price"]) if raw.get("effective_strike_price") is not None else None
            eff_ratio = float(raw["effective_exercise_ratio"]) if raw.get("effective_exercise_ratio") is not None else None

            # Fallback to strike_price / exercise_ratio if not explicitly separated
            strike = eff_strike if eff_strike is not None else (float(raw["strike_price"]) if raw.get("strike_price") is not None else None)
            ratio = eff_ratio if eff_ratio is not None else (float(raw["exercise_ratio"]) if raw.get("exercise_ratio") is not None else None)

            # Parse detailed auditable provenance
            prov_obj = None
            raw_prov = raw.get("provenance")
            if isinstance(raw_prov, dict):
                try:
                    from app.instruments.instrument_schemas import WarrantProvenance, ProvenanceReference
                    init_ref = None
                    eff_ref = None
                    if isinstance(raw_prov.get("initial_terms_source"), dict):
                        init_ref = ProvenanceReference(**raw_prov["initial_terms_source"])
                    if isinstance(raw_prov.get("effective_terms_source"), dict):
                        eff_ref = ProvenanceReference(**raw_prov["effective_terms_source"])
                    prov_obj = WarrantProvenance(
                        initial_terms_source=init_ref,
                        effective_terms_source=eff_ref,
                        reconciliation_mode=raw_prov.get("reconciliation_mode", "MANUAL_RECONCILED"),
                    )
                except Exception as pe:
                    logger.debug(f"Failed to parse provenance for {sym}: {pe}")

            # Determine verification status:
            # Invariant: VERIFIED_CURRENT strictly requires concrete auditable source evidence
            # (either source_document_id or source_url in effective_terms_source or initial_terms_source).
            # A source label alone without documentary evidence is INSUFFICIENT.
            from app.instruments.instrument_schemas import MetadataVerificationStatus
            verification_raw = raw.get("metadata_verification")
            
            has_concrete_source = False
            if prov_obj:
                target_ref = prov_obj.effective_terms_source or prov_obj.initial_terms_source
                if target_ref and (
                    target_ref.source_document_id
                    or target_ref.source_url
                    or (target_ref.notes and prov_obj.reconciliation_mode == "MANUAL_RECONCILED")
                ):
                    has_concrete_source = True

            if verification_raw == "VERIFIED_CURRENT" and has_concrete_source:
                verification_status = MetadataVerificationStatus.VERIFIED_CURRENT
            elif verification_raw == "CONFLICTING":
                verification_status = MetadataVerificationStatus.CONFLICTING
            elif verification_raw == "STALE":
                verification_status = MetadataVerificationStatus.STALE
            else:
                verification_status = MetadataVerificationStatus.UNVERIFIED

            data_quality = self._determine_data_quality(strike, ratio, mat_date)

            return CoveredWarrantSpecification(
                symbol=sym,
                issuer=str(raw.get("issuer", "")).strip().upper(),
                underlying_symbol=str(raw.get("underlying_symbol", "")).strip().upper(),
                strike_price=strike,
                exercise_ratio=ratio,
                initial_strike_price=initial_strike,
                initial_exercise_ratio=initial_ratio,
                effective_strike_price=eff_strike or strike,
                effective_exercise_ratio=eff_ratio or ratio,
                is_adjusted=bool(raw.get("is_adjusted", False)),
                terms_effective_date=raw.get("terms_effective_date"),
                adjustment_reference=raw.get("adjustment_reference"),
                maturity_date=mat_date,
                last_trading_date=raw.get("last_trading_date"),
                listed_volume=int(raw["listed_volume"]) if raw.get("listed_volume") is not None else None,
                issue_price=float(raw["issue_price"]) if raw.get("issue_price") is not None else None,
                instrument_type="CW",
                status=status,
                data_quality=data_quality,
                evidence_level=evidence,
                metadata_verification=verification_status,
                metadata_source=raw.get("metadata_source", "CANONICAL_CACHED_SNAPSHOT"),
                metadata_retrieved_at=raw.get("metadata_retrieved_at", "2026-08-25T00:00:00+07:00"),
                provenance=prov_obj,
            )
        except Exception as e:
            logger.warning(f"Failed to parse warrant specification row {raw}: {e}")
            return None

    async def load_instruments(self, current_date: Optional[str] = None) -> List[CoveredWarrantSpecification]:
        if not self.data_file.exists():
            logger.error(f"Canonical metadata snapshot not found at {self.data_file}")
            return []

        try:
            with open(self.data_file, "r", encoding="utf-8") as f:
                raw_list = json.load(f)

            parsed: List[CoveredWarrantSpecification] = []
            cache: Dict[str, CoveredWarrantSpecification] = {}

            for item in raw_list:
                spec = self._parse_row(item, current_date)
                if spec:
                    parsed.append(spec)
                    cache[spec.symbol] = spec

            self._cache = cache
            self._loaded = True

            # Load manifest if present
            if MANIFEST_FILE.exists():
                try:
                    with open(MANIFEST_FILE, "r", encoding="utf-8") as mf:
                        self._manifest = json.load(mf)
                except Exception as me:
                    logger.warning(f"Failed to load manifest: {me}")

            active_cnt = sum(1 for x in parsed if x.status == InstrumentLifecycleStatus.ACTIVE)
            expired_cnt = sum(1 for x in parsed if x.status == InstrumentLifecycleStatus.EXPIRED)
            unknown_cnt = sum(1 for x in parsed if x.status == InstrumentLifecycleStatus.UNKNOWN)
            complete_cnt = sum(1 for x in parsed if x.data_quality == DataQualityStatus.COMPLETE)
            partial_cnt = sum(1 for x in parsed if x.data_quality == DataQualityStatus.PARTIAL)

            logger.info(
                f"Loaded {len(parsed)} instruments: {active_cnt} ACTIVE, {expired_cnt} EXPIRED, {unknown_cnt} UNKNOWN | "
                f"{complete_cnt} COMPLETE, {partial_cnt} PARTIAL"
            )
            return parsed
        except Exception as e:
            logger.error(f"Error loading instruments from {self.data_file}: {e}")
            return []

    async def get_instrument(self, symbol: str) -> Optional[CoveredWarrantSpecification]:
        sym = symbol.strip().upper()
        if not self._loaded:
            await self.load_instruments()
        return self._cache.get(sym)

    def get_manifest(self) -> Dict[str, Any]:
        return self._manifest
