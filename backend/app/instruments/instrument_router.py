"""
REST API Router for Instrument Registry.
Provides discovery, search, filtering, specification, and coverage reconciliation endpoints.
"""

import logging
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query, Body, status

from app.instruments.instrument_schemas import (
    CoveredWarrantSpecification,
    InstrumentQueryResponse,
    InstrumentLifecycleStatus,
    DataQualityStatus,
    CoverageMetrics,
    ReconciliationReport,
)
from app.instruments.instrument_registry import instrument_registry

logger = logging.getLogger(__name__)
instruments_router = APIRouter(prefix="/api/instruments", tags=["instruments"])


@instruments_router.get("", response_model=InstrumentQueryResponse)
async def list_instruments(
    search: Optional[str] = Query(default=None, description="Text search matching symbol, underlying, or issuer"),
    underlying: Optional[str] = Query(default=None, description="Filter by underlying ticker (e.g. HPG)"),
    issuer: Optional[str] = Query(default=None, description="Filter by issuer (e.g. SSI, VND)"),
    status: Optional[str] = Query(default=None, description="Lifecycle status filter: ACTIVE | EXPIRED | ALL"),
    quality: Optional[str] = Query(default=None, description="Data quality filter: COMPLETE | PARTIAL | ALL"),
    active_only: bool = Query(default=True, description="When true, returns only currently active warrants"),
    verified_only: bool = Query(default=False, description="When true, returns only VERIFIED_CURRENT warrants"),
):
    """
    Lists Covered Warrants in the registry with multi-attribute filtering.
    """
    lifecycle_status = None
    effective_active_only = active_only

    if status:
        stat_upper = status.strip().upper()
        if stat_upper == "ACTIVE":
            lifecycle_status = InstrumentLifecycleStatus.ACTIVE
            effective_active_only = True
        elif stat_upper == "EXPIRED":
            lifecycle_status = InstrumentLifecycleStatus.EXPIRED
            effective_active_only = False
        elif stat_upper in ("ALL", "*"):
            lifecycle_status = None
            effective_active_only = False

    data_quality_filter = None
    if quality:
        q_upper = quality.strip().upper()
        if q_upper == "COMPLETE":
            data_quality_filter = DataQualityStatus.COMPLETE
        elif q_upper == "PARTIAL":
            data_quality_filter = DataQualityStatus.PARTIAL

    items = await instrument_registry.search(
        query=search,
        underlying=underlying,
        issuer=issuer,
        status=lifecycle_status,
        data_quality=data_quality_filter,
        active_only=effective_active_only,
        verified_only=verified_only,
    )

    all_active = await instrument_registry.search(active_only=True)
    coverage = instrument_registry.get_coverage_metrics()

    return InstrumentQueryResponse(
        total=len(items),
        active_count=len(all_active),
        coverage=coverage,
        items=items,
    )


@instruments_router.get("/default-universe")
async def get_default_universe():
    """The curated default research/demo universe (Step 13C).

    Anonymous users and new sessions seed their dashboard from this list instead of a
    hardcoded frontend constant. Every CW here is active and VERIFIED_CURRENT; the list also carries
    its three stock underlyings so the demo can show real underlying relationships and
    quant analytics. Each item is re-resolved against the live registry so a symbol whose
    verification later regresses is dropped rather than shown stale.
    """
    import json
    from pathlib import Path

    from app.instruments.instrument_schemas import MetadataVerificationStatus
    from app.instruments.providers.canonical_provider import get_vietnam_today

    raw = json.loads((Path(__file__).parent / "data" / "default_research_universe.json").read_text())
    if not instrument_registry._is_initialized:
        await instrument_registry.initialize()

    today = get_vietnam_today()
    resolved: list[dict] = []
    for item in raw.get("items", []):
        sym = str(item.get("symbol", "")).strip().upper()
        if not sym:
            continue
        entry = {"symbol": sym, "instrument_type": item.get("instrument_type", "STOCK")}
        if entry["instrument_type"] == "CW":
            spec = await instrument_registry.get_instrument(sym)
            if (spec is None
                or spec.status != InstrumentLifecycleStatus.ACTIVE
                or spec.metadata_verification != MetadataVerificationStatus.VERIFIED_CURRENT
                or (spec.last_trading_date and spec.last_trading_date < today)):
                continue  # Do not seed expired, stopped-trading or unverified contracts.
            entry.update(
                underlying_symbol=spec.underlying_symbol,
                issuer=spec.issuer,
                strike_price=spec.effective_strike,
                exercise_ratio=spec.effective_ratio,
                maturity_date=spec.maturity_date,
                last_trading_date=spec.last_trading_date,
                metadata_verification=spec.metadata_verification.value,
                data_quality=spec.data_quality.value if spec.data_quality else None,
            )
        else:
            entry["underlying_symbol"] = item.get("underlying_symbol")
        resolved.append(entry)

    return {"known_through": raw.get("known_through"), "items": resolved}


@instruments_router.get("/metrics/coverage", response_model=CoverageMetrics)
async def get_coverage_metrics():
    """Returns coverage and completeness metrics for the registry."""
    if not instrument_registry._is_initialized:
        await instrument_registry.initialize()
    return instrument_registry.get_coverage_metrics()


@instruments_router.post("/reconcile", response_model=ReconciliationReport)
async def reconcile_symbols(
    discovered_symbols: List[str] = Body(..., description="List of active symbols discovered from external feed")
):
    """
    Reconciles an external list of discovered symbols against the current registry.
    Identifies missing symbols and computes coverage ratio.
    """
    from app.core.config import settings

    cap = settings.INSTRUMENTS_RECONCILE_MAX_SYMBOLS
    if len(discovered_symbols) > cap:
        raise HTTPException(status_code=400, detail=f"Too many symbols ({len(discovered_symbols)}); max {cap}.")
    if not instrument_registry._is_initialized:
        await instrument_registry.initialize()
    return instrument_registry.reconcile_with_discovered(discovered_symbols)


@instruments_router.get("/meta/underlyings", response_model=List[str])
async def list_underlyings(
    active_only: bool = Query(default=True, description="When true, returns only underlyings of active CWs")
):
    """Returns list of unique underlying equity symbols."""
    return await instrument_registry.get_underlyings(active_only=active_only)


@instruments_router.get("/meta/issuers", response_model=List[str])
async def list_issuers(
    active_only: bool = Query(default=True, description="When true, returns only issuers of active CWs")
):
    """Returns list of unique issuing securities firms."""
    return await instrument_registry.get_issuers(active_only=active_only)


@instruments_router.get("/{symbol}", response_model=CoveredWarrantSpecification)
async def get_instrument(symbol: str):
    """Retrieves full specification for a single Covered Warrant by symbol."""
    spec = await instrument_registry.get_instrument(symbol)
    if not spec:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Instrument '{symbol.upper()}' not found in registry",
        )
    return spec
