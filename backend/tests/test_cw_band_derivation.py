"""CW ceiling/floor are reconstructed from the underlying (get_ceilingfloor omits CWs)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.market_data.market_snapshot_resolver import MarketSnapshotResolver, ResolvedRow
from app.market_data.temporal import DataSource, DataTemporalState, FieldProvenance

pytestmark = pytest.mark.asyncio


def _spec(underlying="HPG", ratio=2.0):
    return SimpleNamespace(underlying_symbol=underlying, effective_ratio=ratio)


def _underlying_row():
    return ResolvedRow(
        symbol="HPG", instrument_type="STOCK",
        values={"reference_price": 21600.0, "ceiling_price": 23100.0, "floor_price": 20100.0},
    )


def _cw_row(**values):
    base = {"reference_price": 1100.0}
    base.update(values)
    return ResolvedRow(
        symbol="CHPG2627", instrument_type="CW", underlying_symbol="HPG", values=base,
        reference_prov=FieldProvenance(DataTemporalState.DERIVED, DataSource.SESSION_REFERENCE),
    )


async def test_bands_derived_from_underlying_limit_over_ratio(monkeypatch):
    monkeypatch.setattr(
        "app.market_data.market_snapshot_resolver.instrument_registry.get_instrument",
        AsyncMock(return_value=_spec(ratio=2.0)),
    )
    cw = _cw_row()
    await MarketSnapshotResolver()._derive_cw_bands([_underlying_row(), cw])
    # 1100 + (23100 - 21600) / 2 = 1850 ; 1100 - (21600 - 20100) / 2 = 350
    assert cw.values["ceiling_price"] == 1850.0
    assert cw.values["floor_price"] == 350.0
    assert "underlying" in (cw.reference_prov.note or "")


async def test_bands_left_null_when_ratio_is_missing(monkeypatch):
    monkeypatch.setattr(
        "app.market_data.market_snapshot_resolver.instrument_registry.get_instrument",
        AsyncMock(return_value=_spec(ratio=None)),
    )
    cw = _cw_row()
    await MarketSnapshotResolver()._derive_cw_bands([_underlying_row(), cw])
    assert cw.values.get("ceiling_price") is None
    assert cw.values.get("floor_price") is None


async def test_existing_bands_are_never_overwritten(monkeypatch):
    monkeypatch.setattr(
        "app.market_data.market_snapshot_resolver.instrument_registry.get_instrument",
        AsyncMock(return_value=_spec()),
    )
    cw = _cw_row(ceiling_price=9999.0)
    await MarketSnapshotResolver()._derive_cw_bands([_underlying_row(), cw])
    assert cw.values["ceiling_price"] == 9999.0


async def test_floor_never_below_one_tick(monkeypatch):
    monkeypatch.setattr(
        "app.market_data.market_snapshot_resolver.instrument_registry.get_instrument",
        AsyncMock(return_value=_spec(ratio=1.0)),
    )
    # ratio 1 -> full underlying move; a deep-OTM CW floor would go negative -> clamp to 10
    cw = _cw_row(reference_price=200.0)
    await MarketSnapshotResolver()._derive_cw_bands([_underlying_row(), cw])
    assert cw.values["floor_price"] == 10.0
