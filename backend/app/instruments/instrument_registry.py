"""
Instrument Registry Repository & Indexing Engine.
Provides thread-safe in-memory querying, multi-attribute filtering,
strict lifecycle separation (ACTIVE vs EXPIRED vs UNKNOWN),
and data completeness metrics for Covered Warrants.
"""

import asyncio
import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Set, Any
from app.instruments.instrument_schemas import (
    CoveredWarrantSpecification,
    InstrumentLifecycleStatus,
    DataQualityStatus,
    LifecycleEvidenceLevel,
    CoverageMetrics,
    ReconciliationReport,
)
from app.instruments.providers.base import InstrumentRegistryProvider
from app.instruments.providers.canonical_provider import CanonicalInstrumentProvider

logger = logging.getLogger(__name__)


class InstrumentRegistry:
    def __init__(self, provider: Optional[InstrumentRegistryProvider] = None):
        self.provider: InstrumentRegistryProvider = provider or CanonicalInstrumentProvider()
        self._instruments: Dict[str, CoveredWarrantSpecification] = {}
        self._underlying_index: Dict[str, Set[str]] = {}
        self._issuer_index: Dict[str, Set[str]] = {}
        self._is_initialized = False
        self._lock = asyncio.Lock()

    async def initialize(self, current_date: Optional[str] = None) -> None:
        """Loads and indexes instruments into in-memory store."""
        async with self._lock:
            if isinstance(self.provider, CanonicalInstrumentProvider):
                items = await self.provider.load_instruments(current_date=current_date)
            else:
                items = await self.provider.load_instruments()

            self._instruments.clear()
            self._underlying_index.clear()
            self._issuer_index.clear()

            for spec in items:
                sym = spec.symbol.upper()
                self._instruments[sym] = spec

                und = spec.underlying_symbol.upper()
                if und:
                    if und not in self._underlying_index:
                        self._underlying_index[und] = set()
                    self._underlying_index[und].add(sym)

                iss = spec.issuer.upper()
                if iss:
                    if iss not in self._issuer_index:
                        self._issuer_index[iss] = set()
                    self._issuer_index[iss].add(sym)

            self._is_initialized = True
            m = self.get_coverage_metrics()
            logger.info(
                f"Instrument Registry initialized: {m.total_discovered_symbols} discovered | "
                f"{m.verified_active_symbols} ACTIVE, {m.verified_expired_symbols} EXPIRED, {m.unknown_lifecycle_symbols} UNKNOWN | "
                f"{m.metadata_complete_symbols} COMPLETE, {m.metadata_partial_symbols} PARTIAL"
            )

    async def get_instrument(self, symbol: str) -> Optional[CoveredWarrantSpecification]:
        if not self._is_initialized:
            await self.initialize()
        return self._instruments.get(symbol.strip().upper())

    def underlying_of(self, symbol: str) -> Optional[str]:
        """Synchronous best-effort: the CW's underlying ticker, or None if not a known CW.
        Reads the already-loaded index only (no init) - safe on a hot request path."""
        spec = self._instruments.get(symbol.strip().upper())
        return spec.underlying_symbol.upper() if (spec and spec.underlying_symbol) else None

    def warrants_for_underlying(self, underlying: str) -> Set[str]:
        """Synchronous best-effort: all known CW symbols on ``underlying`` (empty if none
        loaded / unknown). Reads the already-loaded index only."""
        return set(self._underlying_index.get(underlying.strip().upper(), set()))

    async def search(
        self,
        query: Optional[str] = None,
        underlying: Optional[str] = None,
        issuer: Optional[str] = None,
        status: Optional[InstrumentLifecycleStatus] = None,
        data_quality: Optional[DataQualityStatus] = None,
        evidence_level: Optional[LifecycleEvidenceLevel] = None,
        active_only: bool = True,
        verified_only: bool = False,
    ) -> List[CoveredWarrantSpecification]:
        """
        Queries instruments with multi-attribute filtering.
        Invariants:
        - When active_only=True and status is None, strictly returns status == ACTIVE.
        - Excludes UNKNOWN and EXPIRED from active_only default search.
        """
        if not self._is_initialized:
            await self.initialize()

        results = list(self._instruments.values())

        # 1. Lifecycle filter
        if status:
            results = [spec for spec in results if spec.status == status]
        elif active_only:
            results = [spec for spec in results if spec.status == InstrumentLifecycleStatus.ACTIVE]

        # 2. Data quality filter
        if data_quality:
            results = [spec for spec in results if spec.data_quality == data_quality]

        # 3. Evidence level filter
        if evidence_level:
            results = [spec for spec in results if spec.evidence_level == evidence_level]

        if verified_only:
            from app.instruments.instrument_schemas import MetadataVerificationStatus

            results = [
                spec for spec in results
                if spec.metadata_verification == MetadataVerificationStatus.VERIFIED_CURRENT
            ]

        # 4. Underlying filter
        if underlying:
            und_clean = underlying.strip().upper()
            results = [spec for spec in results if spec.underlying_symbol == und_clean]

        # 5. Issuer filter
        if issuer:
            iss_clean = issuer.strip().upper()
            results = [spec for spec in results if spec.issuer == iss_clean]

        # 6. Text Search filter (matches symbol, underlying, or issuer)
        if query:
            q_clean = query.strip().upper()
            results = [
                spec
                for spec in results
                if q_clean in spec.symbol
                or (spec.underlying_symbol and q_clean in spec.underlying_symbol)
                or (spec.issuer and q_clean in spec.issuer)
            ]

        # Deterministic sorting by symbol
        return sorted(results, key=lambda x: x.symbol)

    async def reconcile_current_market_warrants(
        self,
        symbols: List[str],
        *,
        source: str = "VNSTOCK_CURRENT_CW_GROUP",
        observed_at: Optional[str] = None,
        terms_by_symbol: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> int:
        """Overlay danh sách CW hiện hành đầy đủ lên metadata registry.

        Tư cách niêm yết là bằng chứng lifecycle, nhưng không xác nhận strike, ratio,
        issuer hay maturity. Terms đã xác minh được giữ nguyên; mã mới vào trạng thái
        ACTIVE/PARTIAL/UNVERIFIED cho đến khi terms được đối soát riêng. Mã bị loại khỏi
        danh sách provider được hạ về UNKNOWN, không tự kết luận hết hạn.
        """
        if not self._is_initialized:
            await self.initialize()

        from app.instruments.instrument_schemas import MetadataVerificationStatus

        clean = sorted({str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()})
        live = {symbol for symbol in clean if re.fullmatch(r"C[A-Z]{3}\d{4}", symbol)}
        stamp = observed_at or datetime.now(timezone(timedelta(hours=7))).isoformat()
        current_terms = {
            str(symbol).strip().upper(): value
            for symbol, value in (terms_by_symbol or {}).items()
            if str(symbol).strip().upper() in live and isinstance(value, dict)
        }

        async with self._lock:
            updated = dict(self._instruments)
            for symbol, spec in list(updated.items()):
                if symbol in live:
                    payload = spec.model_dump()
                    payload.update({
                        "status": InstrumentLifecycleStatus.ACTIVE,
                        "evidence_level": LifecycleEvidenceLevel.CURRENT_BROKER_MARKET_LIST,
                    })
                    if symbol in current_terms:
                        payload.update(current_terms[symbol])
                        # Keep higher-quality manually reconciled disclosure references
                        # and corporate-action history. The current broker row refreshes
                        # the effective numbers and verification timestamp without
                        # erasing the original/effective source distinction.
                        if (
                            spec.metadata_verification
                            == MetadataVerificationStatus.VERIFIED_CURRENT
                            and spec.provenance is not None
                        ):
                            payload.update({
                                "initial_strike_price": spec.initial_strike_price,
                                "initial_exercise_ratio": spec.initial_exercise_ratio,
                                "is_adjusted": spec.is_adjusted,
                                "terms_effective_date": spec.terms_effective_date,
                                "adjustment_reference": spec.adjustment_reference,
                                "provenance": spec.provenance.model_dump(),
                                "metadata_source": spec.metadata_source,
                            })
                    updated[symbol] = CoveredWarrantSpecification.model_validate(payload)
                elif (
                    spec.status == InstrumentLifecycleStatus.ACTIVE
                    and spec.evidence_level
                    in {
                        LifecycleEvidenceLevel.CURRENT_PROVIDER_LIST,
                        LifecycleEvidenceLevel.CURRENT_BROKER_MARKET_LIST,
                    }
                ):
                    updated[symbol] = spec.model_copy(update={
                        "status": InstrumentLifecycleStatus.UNKNOWN,
                        "evidence_level": LifecycleEvidenceLevel.SEARCH_ONLY,
                    })

            for symbol in live - set(updated):
                payload: Dict[str, Any] = dict(
                    symbol=symbol,
                    issuer="",
                    underlying_symbol=symbol[1:4],
                    instrument_type="CW",
                    status=InstrumentLifecycleStatus.ACTIVE,
                    data_quality=DataQualityStatus.PARTIAL,
                    evidence_level=LifecycleEvidenceLevel.CURRENT_BROKER_MARKET_LIST,
                    metadata_verification=MetadataVerificationStatus.UNVERIFIED,
                    metadata_source=source,
                    metadata_retrieved_at=stamp,
                )
                if symbol in current_terms:
                    payload.update(current_terms[symbol])
                updated[symbol] = CoveredWarrantSpecification.model_validate(payload)

            self._instruments = updated
            self._underlying_index.clear()
            self._issuer_index.clear()
            for symbol, spec in updated.items():
                underlying = spec.underlying_symbol.strip().upper()
                if underlying:
                    self._underlying_index.setdefault(underlying, set()).add(symbol)
                issuer = spec.issuer.strip().upper()
                if issuer:
                    self._issuer_index.setdefault(issuer, set()).add(symbol)

        return len(live)

    def get_coverage_metrics(self) -> CoverageMetrics:
        from app.instruments.instrument_schemas import MetadataVerificationStatus

        total = len(self._instruments)
        active = sum(1 for spec in self._instruments.values() if spec.status == InstrumentLifecycleStatus.ACTIVE)
        expired = sum(1 for spec in self._instruments.values() if spec.status == InstrumentLifecycleStatus.EXPIRED)
        unknown = sum(1 for spec in self._instruments.values() if spec.status == InstrumentLifecycleStatus.UNKNOWN)

        complete = sum(1 for spec in self._instruments.values() if spec.data_quality == DataQualityStatus.COMPLETE)
        partial = sum(1 for spec in self._instruments.values() if spec.data_quality == DataQualityStatus.PARTIAL)

        ver_current = sum(1 for spec in self._instruments.values() if spec.metadata_verification == MetadataVerificationStatus.VERIFIED_CURRENT)
        unverified = sum(1 for spec in self._instruments.values() if spec.metadata_verification == MetadataVerificationStatus.UNVERIFIED)
        conflicting = sum(1 for spec in self._instruments.values() if spec.metadata_verification == MetadataVerificationStatus.CONFLICTING)
        stale = sum(1 for spec in self._instruments.values() if spec.metadata_verification == MetadataVerificationStatus.STALE)
        adjusted = sum(1 for spec in self._instruments.values() if spec.is_adjusted)

        return CoverageMetrics(
            total_discovered_symbols=total,
            verified_active_symbols=active,
            verified_expired_symbols=expired,
            unknown_lifecycle_symbols=unknown,
            metadata_complete_symbols=complete,
            metadata_partial_symbols=partial,
            verified_current_metadata_symbols=ver_current,
            unverified_metadata_symbols=unverified,
            conflicting_metadata_symbols=conflicting,
            stale_metadata_symbols=stale,
            adjusted_corporate_action_symbols=adjusted,
        )

    def reconcile_with_discovered(self, discovered_symbols: List[str]) -> ReconciliationReport:
        disc_set = set(s.strip().upper() for s in discovered_symbols if s)
        reg_active_set = set(
            sym for sym, spec in self._instruments.items() if spec.status == InstrumentLifecycleStatus.ACTIVE
        )

        common = disc_set.intersection(reg_active_set)
        missing_in_reg = sorted(list(disc_set - reg_active_set))
        missing_in_disc = sorted(list(reg_active_set - disc_set))

        total_disc = len(disc_set)
        cov_pct = (len(common) / total_disc * 100.0) if total_disc > 0 else 100.0

        return ReconciliationReport(
            discovered_count=total_disc,
            registry_active_count=len(reg_active_set),
            common_count=len(common),
            missing_in_registry=missing_in_reg,
            missing_in_discovered=missing_in_disc,
            coverage_percentage=round(cov_pct, 2),
        )

    async def get_underlyings(self, active_only: bool = True) -> List[str]:
        if not self._is_initialized:
            await self.initialize()

        if not active_only:
            return sorted(list(self._underlying_index.keys()))

        active_unds: Set[str] = set()
        for und, syms in self._underlying_index.items():
            if any(self._instruments[s].status == InstrumentLifecycleStatus.ACTIVE for s in syms if s in self._instruments):
                active_unds.add(und)
        return sorted(list(active_unds))

    async def get_issuers(self, active_only: bool = True) -> List[str]:
        if not self._is_initialized:
            await self.initialize()

        if not active_only:
            return sorted(list(self._issuer_index.keys()))

        active_issuers: Set[str] = set()
        for iss, syms in self._issuer_index.items():
            if any(self._instruments[s].status == InstrumentLifecycleStatus.ACTIVE for s in syms if s in self._instruments):
                active_issuers.add(iss)
        return sorted(list(active_issuers))


# Global singleton instance
instrument_registry = InstrumentRegistry()
