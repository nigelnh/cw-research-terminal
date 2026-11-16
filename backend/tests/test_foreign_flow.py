"""Foreign investor buy / sell volume and remaining room, carried from the KBS price board.

The SSI stream has no foreign fields, so the board poll is their only source: they must
reach MarketState, the wire patch and snapshot, and the off-stream resolver row, and a
board row that is older than the last streamed match must still keep them current.
"""

from __future__ import annotations

import pytest

from app.market_data.market_state import MarketState
from app.market_data.providers.vnstock_provider import VnstockProvider, _board_quote

from tests.test_off_stream_board_quotes import (  # noqa: F401 - autouse fixture
    IN_SESSION,
    Fetch,
    board_quote,
    no_live_quotes,
    resolver,
)

SESSION = "2026-11-13"


def board_event(**over):
    """What the provider's board poll emits for one stock (see `_trade_event`)."""
    return {
        "Ticker": "HPG", "Close": 21100, "Reference": 21000, "TotalMatchVolume": 9_460_100,
        "ForeignBuyVolume": 1_633_200, "ForeignSellVolume": 470_100,
        "ForeignRoom": 2_292_162_142, "TradingDate": SESSION,
        "Timestamp": f"{SESSION}T10:00:00+07:00", "_synthetic_session_snapshot": True,
        **over,
    }


def test_the_board_trade_event_carries_the_foreign_fields():
    row = {
        "close_price": 21100, "reference_price": 21000, "volume_accumulated": 9_460_100,
        "foreign_buy_volume": 1_633_200, "foreign_sell_volume": 470_100,
        "foreign_room": 2_292_162_142,
    }
    event = VnstockProvider._trade_event(row, "HPG", SESSION, f"{SESSION}T10:00:00+07:00")
    assert (event["ForeignBuyVolume"], event["ForeignSellVolume"], event["ForeignRoom"]) == (
        1_633_200, 470_100, 2_292_162_142)


def test_the_off_stream_board_quote_keeps_zero_and_drops_a_negative_count():
    quote = _board_quote(
        {"foreign_buy_volume": 0, "foreign_sell_volume": -5, "foreign_room": 425_534_401},
        SESSION,
    )
    assert quote["foreign_buy_volume"] == 0
    assert quote["foreign_sell_volume"] is None
    assert quote["foreign_room"] == 425_534_401


def test_a_board_event_writes_the_foreign_fields_into_the_patch_and_snapshot():
    state = MarketState()
    quote, diff = state.apply_trade_event(board_event())

    assert (quote.foreign_buy_volume, quote.foreign_sell_volume, quote.foreign_room) == (
        1_633_200, 470_100, 2_292_162_142)
    patch = quote.to_wire_patch(diff)
    assert (patch["Foreign_Buy_Vol"], patch["Foreign_Sell_Vol"], patch["Foreign_Room"]) == (
        1_633_200, 470_100, 2_292_162_142)
    row = quote.to_wire_snapshot_row()
    assert (row["Foreign_Buy_Vol"], row["Foreign_Sell_Vol"], row["Foreign_Room"]) == (
        1_633_200, 470_100, 2_292_162_142)
    assert quote.to_wire_snapshot_row(display_eligible=False)["Foreign_Buy_Vol"] is None


def test_a_stream_event_without_foreign_fields_leaves_them_alone():
    state = MarketState()
    state.apply_trade_event(board_event())
    _quote, diff = state.apply_trade_event({
        "Ticker": "HPG", "Close": 21150, "MatchVolume": 100, "TradingDate": SESSION,
        "Timestamp": f"{SESSION}T10:00:05+07:00",
    })
    quote = state.get_quote("HPG")
    assert quote.last_price == 21150
    assert quote.foreign_buy_volume == 1_633_200
    assert not {"foreign_buy_volume", "foreign_sell_volume", "foreign_room"} & set(diff)


def test_a_board_row_older_than_the_last_streamed_match_still_updates_foreign_flow():
    state = MarketState()
    state.apply_trade_event({
        "Ticker": "HPG", "Close": 21150, "MatchVolume": 100, "TradingDate": SESSION,
        "Timestamp": f"{SESSION}T10:00:05+07:00",
    })
    quote, diff = state.apply_trade_event(board_event(Close=21000))

    assert quote.last_price == 21150  # the older board row never rolls the trade back
    assert "last_price" not in diff
    assert diff["foreign_buy_volume"] == 1_633_200
    assert quote.foreign_room == 2_292_162_142


def test_an_older_sessions_board_row_never_writes_foreign_flow():
    state = MarketState()
    state.apply_trade_event({
        "Ticker": "HPG", "Close": 21150, "MatchVolume": 100, "TradingDate": SESSION,
        "Timestamp": f"{SESSION}T10:00:05+07:00",
    })
    _quote, diff = state.apply_trade_event(board_event(
        TradingDate="2026-11-12", Timestamp="2026-11-12T14:45:00+07:00"))
    assert diff == {}
    assert state.get_quote("HPG").foreign_buy_volume is None


def test_a_new_session_clears_the_volumes_but_keeps_the_room():
    state = MarketState()
    state.apply_trade_event(board_event())
    _quote, diff = state.apply_trade_event({
        "Ticker": "HPG", "Reference": 21100, "TradingDate": "2026-11-16",
        "Timestamp": "2026-11-16T08:30:00+07:00",
    })
    quote = state.get_quote("HPG")
    assert quote.foreign_buy_volume is None and quote.foreign_sell_volume is None
    assert diff["foreign_buy_volume"] is None
    assert quote.foreign_room == 2_292_162_142


@pytest.mark.asyncio
async def test_the_off_stream_resolver_row_sends_the_foreign_fields():
    fetch = Fetch({"NVL": await board_quote(
        foreign_buy_volume=125_000, foreign_sell_volume=0, foreign_room=600_000_000)})
    wire = (await resolver(fetch).resolve_rows(["NVL"], now=IN_SESSION))[0].to_wire()
    assert (wire["Foreign_Buy_Vol"], wire["Foreign_Sell_Vol"], wire["Foreign_Room"]) == (
        125_000, 0, 600_000_000)
