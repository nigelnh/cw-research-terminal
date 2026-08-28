from __future__ import annotations

import pytest

from app.persistence.repositories.instrument_repository import InstrumentRepository, InstrumentUpsert

pytestmark = pytest.mark.asyncio


async def test_upsert_inserts_then_updates_same_row(db):
    repo = InstrumentRepository(db)
    async with db.begin():
        row1 = await repo.upsert(InstrumentUpsert(symbol="hpg", instrument_type="STOCK"))
    assert row1.symbol == "HPG"
    assert row1.instrument_type == "STOCK"
    first_id = row1.id

    async with db.begin():
        row2 = await repo.upsert(
            InstrumentUpsert(symbol="HPG", instrument_type="STOCK", is_active=False, metadata={"issuer": None})
        )
    assert row2.id == first_id           # identity is stable
    assert row2.is_active is False        # field updated
    assert row2.updated_at >= row1.updated_at

    async with db.begin():
        assert len(await repo.list_active("STOCK")) == 0  # HPG is now inactive
        all_stock = await repo.get_by_symbol("HPG")
    assert all_stock is not None and all_stock.id == first_id


async def test_underlying_relationship_resolves_when_present(db):
    repo = InstrumentRepository(db)
    async with db.begin():
        # CW inserted before its underlying exists -> underlying_instrument_id stays NULL
        cw_early = await repo.upsert(InstrumentUpsert(symbol="CHPG2601", instrument_type="CW", underlying_symbol="HPG"))
        assert cw_early.underlying_instrument_id is None

        hpg = await repo.upsert(InstrumentUpsert(symbol="HPG", instrument_type="STOCK"))
        cw_late = await repo.upsert(InstrumentUpsert(symbol="CHPG2601", instrument_type="CW", underlying_symbol="HPG"))
    assert cw_late.underlying_instrument_id == hpg.id
    assert cw_late.id == cw_early.id


async def test_upsert_does_not_clobber_underlying_with_null(db):
    repo = InstrumentRepository(db)
    async with db.begin():
        await repo.upsert(InstrumentUpsert(symbol="HPG", instrument_type="STOCK"))
        linked = await repo.upsert(InstrumentUpsert(symbol="CHPG2601", instrument_type="CW", underlying_symbol="HPG"))
        assert linked.underlying_instrument_id is not None
        # a later metadata-only upsert without underlying_symbol must keep the link
        again = await repo.upsert(InstrumentUpsert(symbol="CHPG2601", instrument_type="CW", metadata={"x": 1}))
    assert again.underlying_instrument_id == linked.underlying_instrument_id


async def test_bulk_upsert_and_list_active(db):
    repo = InstrumentRepository(db)
    specs = [
        InstrumentUpsert(symbol="HPG", instrument_type="STOCK"),
        InstrumentUpsert(symbol="FPT", instrument_type="STOCK"),
        InstrumentUpsert(symbol="VNINDEX", instrument_type="INDEX"),
        InstrumentUpsert(symbol="CFPT2601", instrument_type="CW", underlying_symbol="FPT", is_active=False),
    ]
    async with db.begin():
        n = await repo.bulk_upsert(specs)
        active_all = await repo.list_active()
        active_cw = await repo.list_active("CW")
    assert n == 4
    assert {r.symbol for r in active_all} == {"HPG", "FPT", "VNINDEX"}
    assert active_cw == []


async def test_upsert_rejects_bad_type(db):
    repo = InstrumentRepository(db)
    with pytest.raises(ValueError):
        async with db.begin():
            await repo.upsert(InstrumentUpsert(symbol="XXX", instrument_type="BOND"))
