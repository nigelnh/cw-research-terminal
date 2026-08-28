"""Real-PostgreSQL ownership + ordering + validation for the user watchlist repository.

The security invariant under test: a repository call scoped to owner A can never read or
mutate owner B's rows, and the owner key is only ever the argument passed by the caller
(the API layer passes the verified JWT sub) - never anything from a payload.
"""

from __future__ import annotations

import pytest

from app.persistence.repositories.user_watchlist_repository import (
    UserWatchlistRepository,
    WatchlistItemInput,
    WatchlistValidationError,
)

pytestmark = pytest.mark.asyncio

A = "aaaaaaaa-0000-0000-0000-000000000001"
B = "bbbbbbbb-0000-0000-0000-000000000002"


def _items(*symbols: str) -> list[WatchlistItemInput]:
    return [WatchlistItemInput(symbol=s, instrument_type="STOCK") for s in symbols]


async def test_get_for_owner_is_none_before_any_save(db):
    repo = UserWatchlistRepository(db)
    assert await repo.get_for_owner(A) is None


async def test_replace_then_read_preserves_order(db):
    repo = UserWatchlistRepository(db)
    async with db.begin():
        await repo.replace_for_owner(A, _items("HPG", "VHM", "CTCB2601"))
    async with db.begin():
        row = await repo.get_for_owner(A)
    assert [i.symbol for i in row.items] == ["HPG", "VHM", "CTCB2601"]
    assert [i.position for i in row.items] == [0, 1, 2]


async def test_replace_is_a_full_atomic_swap(db):
    repo = UserWatchlistRepository(db)
    async with db.begin():
        await repo.replace_for_owner(A, _items("HPG", "VHM", "SSI", "FPT"))
    async with db.begin():
        await repo.replace_for_owner(A, _items("MWG", "HPG"))
    async with db.begin():
        row = await repo.get_for_owner(A)
    assert [i.symbol for i in row.items] == ["MWG", "HPG"]


async def test_two_owners_are_fully_isolated(db):
    repo = UserWatchlistRepository(db)
    async with db.begin():
        await repo.replace_for_owner(A, _items("HPG", "VHM"))
        await repo.replace_for_owner(B, _items("FPT", "MWG", "SSI"))
    async with db.begin():
        row_a = await repo.get_for_owner(A)
        row_b = await repo.get_for_owner(B)
    assert [i.symbol for i in row_a.items] == ["HPG", "VHM"]
    assert [i.symbol for i in row_b.items] == ["FPT", "MWG", "SSI"]
    # nothing from A leaks into B
    assert not ({"HPG", "VHM"} & {i.symbol for i in row_b.items})


async def test_owner_a_update_does_not_touch_owner_b(db):
    repo = UserWatchlistRepository(db)
    async with db.begin():
        await repo.replace_for_owner(A, _items("HPG"))
        await repo.replace_for_owner(B, _items("FPT", "MWG"))
    async with db.begin():
        await repo.replace_for_owner(A, _items("VHM", "SSI", "VCB"))
    async with db.begin():
        row_b = await repo.get_for_owner(B)
    assert [i.symbol for i in row_b.items] == ["FPT", "MWG"]


async def test_duplicate_symbols_rejected(db):
    repo = UserWatchlistRepository(db)
    with pytest.raises(WatchlistValidationError):
        async with db.begin():
            await repo.replace_for_owner(A, _items("HPG", "hpg"))
    # nothing was written
    async with db.begin():
        assert await repo.get_for_owner(A) is None


async def test_capacity_enforced(db):
    repo = UserWatchlistRepository(db, max_items=3)
    with pytest.raises(WatchlistValidationError):
        async with db.begin():
            await repo.replace_for_owner(A, _items("A1", "B2", "C3", "D4"))


async def test_bad_symbol_rejected(db):
    repo = UserWatchlistRepository(db)
    with pytest.raises(WatchlistValidationError):
        async with db.begin():
            await repo.replace_for_owner(A, [WatchlistItemInput(symbol="!!", instrument_type="STOCK")])


async def test_bad_instrument_type_rejected(db):
    repo = UserWatchlistRepository(db)
    with pytest.raises(WatchlistValidationError):
        async with db.begin():
            await repo.replace_for_owner(
                A, [WatchlistItemInput(symbol="HPG", instrument_type="BOND")]
            )


async def test_validation_failure_rolls_back_partial_write(db):
    repo = UserWatchlistRepository(db)
    async with db.begin():
        await repo.replace_for_owner(A, _items("HPG", "VHM"))
    # a later invalid replace must not destroy the good list
    with pytest.raises(WatchlistValidationError):
        async with db.begin():
            await repo.replace_for_owner(A, _items("SSI", "SSI"))
    async with db.begin():
        row = await repo.get_for_owner(A)
    assert [i.symbol for i in row.items] == ["HPG", "VHM"]


async def test_cw_metadata_round_trips(db):
    from datetime import date

    repo = UserWatchlistRepository(db)
    async with db.begin():
        await repo.replace_for_owner(
            A,
            [
                WatchlistItemInput(
                    symbol="CTCB2601",
                    instrument_type="CW",
                    underlying_symbol="tcb",
                    issuer="KIS",
                    strike_price=25000.0,
                    exercise_ratio=2.0,
                    maturity_date=date(2026, 12, 10),
                )
            ],
        )
    async with db.begin():
        row = await repo.get_for_owner(A)
    item = row.items[0]
    assert item.underlying_symbol == "TCB"
    assert item.strike_price == 25000.0
    assert item.exercise_ratio == 2.0
    assert item.maturity_date == date(2026, 12, 10)
