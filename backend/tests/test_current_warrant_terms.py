import httpx
import pytest

from app.instruments.instrument_registry import InstrumentRegistry
from app.instruments.instrument_schemas import (
    DataQualityStatus,
    InstrumentLifecycleStatus,
    MetadataVerificationStatus,
)
from app.instruments.providers.base import InstrumentRegistryProvider
from app.instruments.providers.vndirect_terms_provider import (
    fetch_current_warrant_terms,
    load_bundled_current_warrant_terms,
)


class _EmptyRegistryProvider(InstrumentRegistryProvider):
    async def load_instruments(self):
        return []

    async def get_instrument(self, symbol: str):
        return None


@pytest.mark.asyncio
async def test_current_terms_normalize_ratio_issuer_and_provenance():
    payload = {
        "data": [
            {
                "code": "CHPG2603",
                "issuer": "TCX",
                "underlyingAsset": "HPG",
                "exercisePrice": 25885,
                "exerciseRatio": "3.5704:1",
                "expiryDate": "2026-12-21",
                "lastTradingDate": "2026-12-17",
                "listedQtty": 8_000_000,
            }
        ],
        "totalPages": 1,
    }
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    async with httpx.AsyncClient(transport=transport) as client:
        terms = await fetch_current_warrant_terms(
            "2026-09-17", base_url="https://finfo.test/v4", client=client
        )

    term = terms["CHPG2603"]
    assert term["issuer"] == "TCBS"
    assert term["strike_price"] == 25885
    assert term["exercise_ratio"] == 3.5704
    assert term["data_quality"] == DataQualityStatus.COMPLETE
    assert term["metadata_verification"] == MetadataVerificationStatus.VERIFIED_CURRENT
    assert "code:CHPG2603" in term["provenance"]["effective_terms_source"]["source_url"]


@pytest.mark.asyncio
async def test_registry_reconcile_makes_current_term_complete_and_quant_ready():
    registry = InstrumentRegistry(provider=_EmptyRegistryProvider())
    await registry.initialize()
    terms = {
        "CHPG2603": {
            "symbol": "CHPG2603",
            "issuer": "TCBS",
            "underlying_symbol": "HPG",
            "strike_price": 25885,
            "exercise_ratio": 3.5704,
            "effective_strike_price": 25885,
            "effective_exercise_ratio": 3.5704,
            "maturity_date": "2026-12-21",
            "last_trading_date": "2026-12-17",
            "status": "ACTIVE",
            "data_quality": "COMPLETE",
            "evidence_level": "CURRENT_BROKER_MARKET_LIST",
            "metadata_verification": "VERIFIED_CURRENT",
            "metadata_source": "VNDIRECT_FINFO_CURRENT_DERIVATIVES",
            "metadata_retrieved_at": "2026-09-17T09:30:00+07:00",
            "provenance": {
                "effective_terms_source": {
                    "source_type": "CURRENT_BROKER_TERMS",
                    "source_url": "https://finfo.test/v4/derivatives?q=code:CHPG2603",
                    "retrieved_at": "2026-09-17T09:30:00+07:00",
                },
                "reconciliation_mode": "AUTOMATIC_SCRAPED",
            },
        }
    }

    await registry.reconcile_current_market_warrants(
        ["CHPG2603"], terms_by_symbol=terms
    )
    spec = await registry.get_instrument("CHPG2603")
    assert spec is not None
    assert spec.status == InstrumentLifecycleStatus.ACTIVE
    assert spec.data_quality == DataQualityStatus.COMPLETE
    assert spec.metadata_verification == MetadataVerificationStatus.VERIFIED_CURRENT
    assert spec.issuer == "TCBS"
    assert spec.effective_strike == 25885
    assert spec.effective_ratio == 3.5704


def test_bundled_terms_cover_current_rows_but_drop_past_last_trading_dates():
    current = load_bundled_current_warrant_terms("2026-09-17")
    assert len(current) == 326
    assert current["CHPG2540"]["issuer"] == "KAFI"
    assert current["CHPG2540"]["exercise_ratio"] == 3.5704
    assert "CHPG2602" not in load_bundled_current_warrant_terms("2026-09-18")
