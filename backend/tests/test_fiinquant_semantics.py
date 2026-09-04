from datetime import datetime

import pytest

from app.market_data.live_bar_builder import LiveBarBuilder
from app.market_data.market_state import MarketState
from app.market_data.market_schemas import CanonicalQuote
from app.market_data.trading_calendar import MarketPhase, VN_TZ, market_phase


def test_trade_mapping_preserves_zero_and_separates_match_session_totals():
    quote, _ = MarketState().apply_trade_event({
        "Ticker": "HPG", "TradingDate": "2026-09-03T09:16:00+07:00",
        "Close": 27_000, "Reference": 27_000, "MatchVolume": 0,
        "TotalMatchVolume": 1_234_567, "TotalMatchValue": 33_333_309_000,
    })
    assert quote.last_price == 27_000
    assert quote.traded_quantity == 0
    assert quote.total_volume == 1_234_567
    assert quote.trading_value == 33_333_309_000
    assert quote.reference_price == 27_000
    assert quote.trade_timestamp == quote.source_timestamp


def test_book_update_does_not_advance_trade_time_or_make_a_trade():
    state = MarketState()
    trade, _ = state.apply_trade_event({
        "Ticker": "HPG", "Timestamp": "2026-09-03T09:16:00+07:00",
        "Close": 27_000, "MatchVolume": 100,
    })
    book, _ = state.apply_bidask_event({
        "Ticker": "HPG", "Timestamp": "2026-09-03T09:17:00+07:00",
        "Best1Bid": 26_950, "Best1Ask": 27_050,
    })
    assert book.trade_timestamp == trade.trade_timestamp
    assert book.book_timestamp > book.trade_timestamp
    assert book.last_price == 27_000


@pytest.mark.parametrize(("clock", "expected"), [
    ((8, 59, 59), MarketPhase.PRE_OPEN), ((9, 0, 0), MarketPhase.ATO),
    ((9, 15, 0), MarketPhase.CONTINUOUS_AM), ((11, 30, 0), MarketPhase.LUNCH_BREAK),
    ((13, 0, 0), MarketPhase.CONTINUOUS_PM), ((14, 30, 0), MarketPhase.ATC),
    ((14, 45, 0), MarketPhase.POST_CLOSE_NEGOTIATED), ((15, 0, 0), MarketPhase.CLOSED),
])
def test_hose_phase_boundaries(clock, expected):
    assert market_phase(datetime(2026, 9, 3, *clock, tzinfo=VN_TZ)) == expected


def test_trade_only_bar_builder_uses_match_volume_and_deduplicates():
    builder = LiveBarBuilder()
    event = {"TradingDate": "2026-09-03T09:16:05+07:00", "Close": 27_000,
             "MatchVolume": 100, "TotalMatchVolume": 10_000}
    patches = builder.on_trade("HPG", event)
    one = next(item for item in patches if item["timeframe"] == "1m")
    assert one["bar"]["volume"] == 100
    assert one["bar"]["open"] == one["bar"]["close"] == 27_000
    assert builder.on_trade("HPG", event) == []


def test_missing_match_volume_stays_unavailable_in_bar():
    patches = LiveBarBuilder().on_trade(
        "HPG", {"Timestamp": "2026-09-03T09:16:05+07:00", "Close": 27_000}
    )
    assert next(item for item in patches if item["timeframe"] == "1m")["bar"]["volume"] is None


def test_preopen_zero_reset_is_not_an_actual_trade_or_candle():
    event = {
        "Ticker": "HPG", "Timestamp": "2026-09-04T08:00:00+07:00",
        "Close": 0, "Open": 0, "High": 0, "Low": 0, "Reference": 21600,
        "MatchVolume": 0, "TotalMatchVolume": 0, "TotalMatchValue": 0,
        "Change": 0,
    }
    quote, _ = MarketState().apply_trade_event(event)
    assert quote.last_price is None
    assert quote.open_price is None
    assert quote.price_change_percent is None
    assert quote.trade_timestamp is None
    assert quote.traded_quantity is None
    assert quote.total_volume == 0
    assert quote.trading_value == 0
    assert quote.reference_price == 21600
    assert LiveBarBuilder().on_trade("HPG", event) == []


def test_legacy_zero_price_cache_does_not_restore_a_fake_trade():
    state = MarketState()
    state.restore_quote(CanonicalQuote(
        symbol="HPG", last_price=0, total_volume=0, traded_quantity=0,
        price_change_percent=-1, trade_timestamp=123, source_timestamp=123,
    ))
    quote = state.get_quote("HPG")
    assert quote.last_price is None
    assert quote.trade_timestamp is None
    assert quote.traded_quantity is None
    assert quote.price_change_percent is None
    assert quote.total_volume == 0
