"""
Canonical Covered Warrant schemas for the Instrument Registry.
Independent from realtime market data providers.
Supports initial vs effective adjusted contract terms and multi-tier provenance verification.
"""

from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class InstrumentLifecycleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"


class DataQualityStatus(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"


class LifecycleEvidenceLevel(str, Enum):
    CURRENT_PROVIDER_LIST = "CURRENT_PROVIDER_LIST"
    CURRENT_EXCHANGE_LIST = "CURRENT_EXCHANGE_LIST"
    CURRENT_BROKER_MARKET_LIST = "CURRENT_BROKER_MARKET_LIST"
    MANUAL_SNAPSHOT = "MANUAL_SNAPSHOT"
    SEARCH_ONLY = "SEARCH_ONLY"
    EXPIRED_BY_DATE = "EXPIRED_BY_DATE"


class MetadataVerificationStatus(str, Enum):
    VERIFIED_CURRENT = "VERIFIED_CURRENT"  # Reconciled against concrete, auditable source notices (URL / Document ID)
    UNVERIFIED = "UNVERIFIED"              # Populated or labeled but lacking auditable source documents
    CONFLICTING = "CONFLICTING"            # Contradicts real-time market data or broker terms
    STALE = "STALE"                        # Exceeds refresh staleness threshold without renewal


class ProvenanceReference(BaseModel):
    source_type: str = Field(..., description="Classification (e.g. VSDC_REGISTRATION, HOSE_CORPORATE_ACTION_NOTICE, MANUAL_RECONCILED_REFERENCE)")
    source_url: Optional[str] = Field(default=None, description="Publicly accessible URL to disclosure/document")
    source_document_id: Optional[str] = Field(default=None, description="Official notice / filing identifier")
    source_published_at: Optional[str] = Field(default=None, description="Document publication date (YYYY-MM-DD)")
    retrieved_at: str = Field(..., description="ISO 8601 timestamp when reference was verified")
    notes: Optional[str] = Field(default=None, description="Auditor / reconciliation notes")


class WarrantProvenance(BaseModel):
    initial_terms_source: Optional[ProvenanceReference] = Field(default=None, description="Issuance/IPO registration evidence")
    effective_terms_source: Optional[ProvenanceReference] = Field(default=None, description="Current corporate action adjustment evidence")
    reconciliation_mode: str = Field(default="MANUAL_RECONCILED", description="AUTOMATIC_SCRAPED | MANUAL_RECONCILED")


class CoveredWarrantSpecification(BaseModel):
    symbol: str = Field(..., description="Canonical warrant ticker (e.g. CHPG2602)")
    issuer: str = Field(..., description="Issuing securities firm (e.g. TCBS, SSI, VND, HSC, KIS, ACBS)")
    underlying_symbol: str = Field(..., description="Underlying equity symbol (e.g. HPG, FPT, MWG)")

    # Canonical effective terms (consumed by QuantEngine and UI)
    strike_price: Optional[float] = Field(default=None, description="Current effective strike price in raw VND")
    exercise_ratio: Optional[float] = Field(
        default=None,
        description="Current effective exercise ratio (e.g. 3.5704 = 3.5704:1)",
    )

    # Initial vs Effective Corporate Action Terms
    initial_strike_price: Optional[float] = Field(default=None, description="Issuance IPO strike price in raw VND")
    initial_exercise_ratio: Optional[float] = Field(default=None, description="Issuance IPO conversion ratio")
    effective_strike_price: Optional[float] = Field(default=None, description="Adjusted strike price after corporate actions")
    effective_exercise_ratio: Optional[float] = Field(default=None, description="Adjusted conversion ratio after corporate actions")
    is_adjusted: bool = Field(default=False, description="True if contract underwent corporate action adjustments")
    terms_effective_date: Optional[str] = Field(default=None, description="Date when current effective terms took effect (YYYY-MM-DD)")
    adjustment_reference: Optional[str] = Field(default=None, description="Corporate action adjustment notice reference")

    # Dates & Volumes
    maturity_date: Optional[str] = Field(default=None, description="Expiration/maturity date in YYYY-MM-DD format")
    last_trading_date: Optional[str] = Field(default=None, description="Last trading date in YYYY-MM-DD format")
    listed_volume: Optional[int] = Field(default=None, description="Total listed issue volume in units")
    issue_price: Optional[float] = Field(default=None, description="Initial IPO issuance price in raw VND")
    instrument_type: str = Field(default="CW", description="Instrument asset class")

    # Lifecycle, Data Completeness & Verification Dimensions
    status: InstrumentLifecycleStatus = Field(
        default=InstrumentLifecycleStatus.UNKNOWN,
        description="Lifecycle status: ACTIVE | EXPIRED | UNKNOWN",
    )
    data_quality: DataQualityStatus = Field(
        default=DataQualityStatus.PARTIAL,
        description="Data completeness: COMPLETE (all K, CR, T present) | PARTIAL",
    )
    evidence_level: LifecycleEvidenceLevel = Field(
        default=LifecycleEvidenceLevel.SEARCH_ONLY,
        description="Evidence grade proving lifecycle status",
    )
    metadata_verification: MetadataVerificationStatus = Field(
        default=MetadataVerificationStatus.UNVERIFIED,
        description="Verification grade: VERIFIED_CURRENT | UNVERIFIED | CONFLICTING | STALE",
    )

    # Provenance
    metadata_source: Optional[str] = Field(
        default=None,
        description="Provenance origin (e.g. HOSE_VSDC_CORPORATE_ACTION_NOTICE, CANONICAL_CACHED_SNAPSHOT)",
    )
    metadata_retrieved_at: Optional[str] = Field(
        default=None,
        description="ISO 8601 timestamp when this record was retrieved/verified",
    )
    provenance: Optional[WarrantProvenance] = Field(
        default=None,
        description="Detailed auditable source references (initial & effective terms documents/URLs)",
    )

    @property
    def effective_strike(self) -> Optional[float]:
        """Returns the current effective strike price."""
        if self.effective_strike_price is not None:
            return self.effective_strike_price
        return self.strike_price

    @property
    def effective_ratio(self) -> Optional[float]:
        """Returns the current effective conversion ratio."""
        if self.effective_exercise_ratio is not None:
            return self.effective_exercise_ratio
        return self.exercise_ratio


class CoverageMetrics(BaseModel):
    total_discovered_symbols: int
    verified_active_symbols: int
    verified_expired_symbols: int
    unknown_lifecycle_symbols: int
    metadata_complete_symbols: int
    metadata_partial_symbols: int
    verified_current_metadata_symbols: int = Field(default=0, description="Count of CWs with VERIFIED_CURRENT metadata")
    unverified_metadata_symbols: int = Field(default=0, description="Count of CWs with UNVERIFIED metadata")
    conflicting_metadata_symbols: int = Field(default=0, description="Count of CWs with CONFLICTING metadata")
    stale_metadata_symbols: int = Field(default=0, description="Count of CWs with STALE metadata")
    adjusted_corporate_action_symbols: int = Field(default=0, description="Count of CWs with adjusted corporate action terms")


class InstrumentQueryResponse(BaseModel):
    total: int = Field(..., description="Total instruments matching query filter")
    active_count: int = Field(..., description="Count of currently active instruments")
    coverage: Optional[CoverageMetrics] = Field(None, description="Registry coverage & data quality metrics")
    items: List[CoveredWarrantSpecification] = Field(..., description="List of warrant specifications")


class ReconciliationReport(BaseModel):
    discovered_count: int
    registry_active_count: int
    common_count: int
    missing_in_registry: List[str]
    missing_in_discovered: List[str]
    coverage_percentage: float
