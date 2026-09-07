"""Time & sales tape: only real matches, an honest derived side, 08:00 ICT retention."""
from datetime import datetime, timedelta

import pytest

from app.market_data.market_state import MarketState
from app.market_data.traded_log import (
    TradedLog, classify_side, seconds_until_rollover, ROLLOVER_HOUR_ICT,
)
from app.market_data.trading_calendar import VN_TZ

pytestmark = pytest.mark.asyncio  # async cases; the pure helpers below are sync


def _state_with_book(bid=21_850, ask=21_900):
    s = MarketState()
    s.apply_bidask_event({"Ticker": "HPG", "Best1Bid": bid, "Best1Ask": ask})
    return s


def _trade(state, price, when="2026-09-07T09:20:00+07:00", vol=300):
    return state.apply_trade_event({
        "Ticker": "HPG", "TradingDate": when, "Close": price,
        "Reference": 21_700, "MatchVolume": vol, "TotalMatchVolume": 1_000_000,
    })


# ------------------------------------------------------------------ side rule
async def test_side_is_derived_from_the_book_and_left_blank_inside_the_spread():
    assert classify_side(21_900, 21_850, 21_900) == "B"   # at the ask
    assert classify_side(21_950, 21_850, 21_900) == "B"   # through the ask
    assert classify_side(21_850, 21_850, 21_900) == "S"   # at the bid
    assert classify_side(21_800, 21_850, 21_900) == "S"
    assert classify_side(21_870, 21_850, 21_900) is None  # genuinely ambiguous
    assert classify_side(21_870, None, None) is None      # no book, no guess


# ------------------------------------------------------------------ retention
async def test_retention_targets_0800_ict_the_next_morning():
    during = datetime(2026, 9, 7, 10, 0, tzinfo=VN_TZ)
    secs = seconds_until_rollover(during)
    assert during + timedelta(seconds=secs) == datetime(2026, 9, 8, ROLLOVER_HOUR_ICT, 0, tzinfo=VN_TZ)


async def test_after_the_close_the_tape_still_survives_the_night():
    evening = datetime(2026, 9, 7, 21, 0, tzinfo=VN_TZ)
    assert seconds_until_rollover(evening) == 11 * 3600


async def test_just_before_rollover_the_window_is_still_positive():
    assert seconds_until_rollover(datetime(2026, 9, 7, 7, 59, tzinfo=VN_TZ)) >= 60


# ---------------------------------------------------------------- recording
async def test_a_match_prints_with_price_change_volume_and_side():
    state = _state_with_book()
    log = TradedLog(max_entries=10)
    quote, diff = _trade(state, 21_900)
    entry = log.record(quote, diff)
    assert entry is not None
    assert entry["price"] == 21_900
    assert entry["volume"] == 300
    assert entry["side"] == "B"          # printed at the ask
    assert entry["time"] == "09:20:00"
    assert entry["change"] == 200        # derived vs the 21,700 reference
    # the state rounds its canonical fraction to 6dp
    assert entry["change_percent"] == pytest.approx(200 / 21_700, abs=1e-6)


async def test_a_frame_that_carries_no_new_match_never_prints():
    """The 20s session poll restates session totals; it must not add a tape row."""
    state = _state_with_book()
    log = TradedLog(max_entries=10)
    quote, diff = _trade(state, 21_900)
    log.record(quote, diff)
    book_quote, book_diff = state.apply_bidask_event({
        "Ticker": "HPG", "Best1Bid": 21_860, "Best1Ask": 21_910,
    })
    assert log.record(book_quote, book_diff) is None
    assert log.get("HPG")["count"] == 1


async def test_the_same_match_redelivered_after_a_reconnect_prints_once():
    state = _state_with_book()
    log = TradedLog(max_entries=10)
    quote, diff = _trade(state, 21_900)
    log.record(quote, diff)
    assert log.record(quote, diff) is None
    assert log.get("HPG")["count"] == 1


async def test_the_tape_is_newest_first_and_bounded():
    state = _state_with_book()
    log = TradedLog(max_entries=3)
    for i, price in enumerate([21_800, 21_850, 21_900, 21_950]):
        q, d = _trade(state, price, when=f"2026-09-07T09:2{i}:00+07:00")
        log.record(q, d)
    items = log.get("HPG")["items"]
    assert [i["price"] for i in items] == [21_950, 21_900, 21_850]  # newest first, capped


async def test_a_new_session_starts_a_clean_tape():
    state = _state_with_book()
    log = TradedLog(max_entries=10)
    q, d = _trade(state, 21_900)
    log.record(q, d)
    q2, d2 = _trade(state, 22_000, when="2026-09-08T09:16:00+07:00")
    log.record(q2, d2)
    tape = log.get("HPG")
    assert tape["count"] == 1
    assert tape["session_date"] == "2026-09-08"


async def test_the_response_declares_the_side_is_derived():
    log = TradedLog()
    assert log.get("HPG")["side_basis"] == "DERIVED_FROM_BOOK"


async def test_a_missing_redis_client_is_not_an_error():
    """The tape degrades to memory-only rather than failing the feed."""
    state = _state_with_book()
    log = TradedLog(max_entries=5)
    q, d = _trade(state, 21_900)
    log.record(q, d)
    await log.persist("HPG")           # no client attached
    assert await log.restore(["HPG"]) == 0
    assert log.get("HPG")["count"] == 1
