"""InstrumentResolver: canonical metadata comes from the registry, unknown symbols are None.

No database needed - the resolver falls back to the InstrumentRegistry (loaded from the
local canonical snapshot) and the curated equity/index allow-lists.
"""

from __future__ import annotations

import pytest

from app.me.instrument_resolver import InstrumentResolver

pytestmark = pytest.mark.asyncio


@pytest.fixture
def resolver() -> InstrumentResolver:
    return InstrumentResolver(session=None)


async def test_covered_warrant_resolves_to_canonical_terms(resolver):
    # CVPB2615 has publicly-reconciled, VERIFIED_CURRENT contract terms.
    r = await resolver.resolve("cvpb2615")
    assert r is not None
    assert r.symbol == "CVPB2615"
    assert r.instrument_type == "CW"
    assert r.underlying_symbol == "VPB"
    assert r.issuer == "ACBS"
    assert r.strike_price == 28500.0
    assert r.exercise_ratio == 2.0
    assert r.maturity_date.isoformat() == "2027-02-17"
    assert r.last_trading_date.isoformat() == "2027-02-15"


async def test_partial_registry_cw_is_still_resolved(resolver):
    # CVPB2501: discovered via public search, no contract terms yet (data_quality PARTIAL).
    r = await resolver.resolve("CVPB2501")
    assert r is not None
    assert r.instrument_type == "CW"
    assert r.underlying_symbol == "VPB"
    assert r.strike_price is None
    assert r.exercise_ratio is None
    assert r.data_quality == "PARTIAL"


async def test_cw_underlying_resolves_as_stock(resolver):
    r = await resolver.resolve("HPG")
    assert r is not None and r.instrument_type == "STOCK"
    assert r.underlying_symbol is None and r.strike_price is None


async def test_curated_equity_not_a_cw_underlying_resolves_as_stock(resolver):
    r = await resolver.resolve("NVL")  # HOSE blue chip, on VN_UNDERLYINGS, not a CW underlying
    assert r is not None and r.instrument_type == "STOCK"


async def test_known_index_resolves_as_index(resolver):
    r = await resolver.resolve("vnindex")
    assert r is not None and r.instrument_type == "INDEX"


@pytest.mark.parametrize("bad", ["ZZZ9NOPE", "NOTREAL", "", "!!", "A", "x" * 40])
async def test_unknown_or_malformed_symbol_is_none(resolver, bad):
    assert await resolver.resolve(bad) is None


async def test_client_cannot_influence_resolution(resolver):
    # resolve() takes only a string - there is no field a client could pass to change it.
    a = await resolver.resolve("CTCB2601")
    b = await resolver.resolve("  ctcb2601 ")
    assert a == b
