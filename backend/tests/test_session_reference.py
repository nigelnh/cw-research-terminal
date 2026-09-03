from datetime import date, datetime, timezone

import pytest

from app.market_data.market_schemas import CanonicalQuote
from app.market_data.market_state import MarketState
from app.market_data.session_reference import refresh_session_references


class _Provider:
    async def get_session_reference_data(self, symbols, session_date):
        return {
            symbol: {
                "session_date": session_date.isoformat(),
                "reference_price": 22_200,
                "ceiling_price": 23_750,
                "floor_price": 20_650,
            }
            for symbol in symbols
        }


class _Store:
    def __init__(self):
        self.saved = {}

    def enqueue_save(self, symbol, quote):
        self.saved[symbol] = quote


@pytest.mark.asyncio
async def test_refresh_merges_static_fields_without_overwriting_newer_live_values():
    state = MarketState()
    store = _Store()
    live_ts = int(datetime(2026, 9, 2, 3, 5, tzinfo=timezone.utc).timestamp() * 1000)
    state.restore_quote(CanonicalQuote(
        symbol="HPG",
        last_price=22_350,
        bid1_price=22_300,
        ask1_price=22_400,
        total_volume=1_500_000,
        source_timestamp=live_ts,
        received_timestamp=live_ts,
    ))

    updates = await refresh_session_references(
        provider=_Provider(), state=state, store=store, symbols=["HPG"],
        session_date=date(2026, 9, 2),
        now=datetime(2026, 9, 2, 3, 6, tzinfo=timezone.utc),
    )

    quote = state.get_quote("HPG")
    assert quote is not None
    assert (quote.last_price, quote.bid1_price, quote.ask1_price) == (22_350, 22_300, 22_400)
    assert (quote.reference_price, quote.ceiling_price, quote.floor_price) == (22_200, 23_750, 20_650)
    assert quote.price_change == 150
    assert quote.reference_session_date == "2026-09-02"
    assert store.saved["HPG"].reference_price == 22_200
    assert updates[0].quote.to_wire_patch(updates[0].diff)["Ref"] == 22.2


def test_older_reference_refresh_cannot_replace_newer_session_metadata():
    state = MarketState()
    state.apply_reference_metadata(
        "HPG", session_date="2026-09-03", reference_price=22_500,
        ceiling_price=24_050, floor_price=20_950,
    )

    quote, diff = state.apply_reference_metadata(
        "HPG", session_date="2026-09-02", reference_price=22_200,
        ceiling_price=23_750, floor_price=20_650,
    )

    assert diff == {}
    assert quote.reference_price == 22_500
    assert quote.reference_session_date == "2026-09-03"


def test_first_tick_of_new_session_expires_old_bands_before_applying_book():
    state = MarketState()
    state.apply_reference_metadata(
        "HPG", session_date="2026-09-02", reference_price=22_200,
        ceiling_price=23_750, floor_price=20_650,
    )
    state.apply_trade_event({
        "Ticker": "HPG",
        "Timestamp": "2026-09-02T14:59:59+07:00",
        "Close": 22_100,
        "Change": -100,
        "ChangePercent": -0.0045,
    })

    quote, diff = state.apply_bidask_event({
        "Ticker": "HPG",
        "Timestamp": "2026-09-03T09:00:01+07:00",
        "Best1Bid": 22_450,
        "Best1Ask": 22_500,
    })

    assert quote.bid1_price == 22_450
    assert quote.reference_price is None
    assert quote.ceiling_price is None
    assert quote.floor_price is None
    assert quote.price_change is None
    assert quote.price_change_percent is None
    assert diff["reference_price"] is None
    assert diff["ceiling_price"] is None
    assert diff["floor_price"] is None
    assert diff["price_change"] is None
    assert diff["price_change_percent"] is None
    assert diff["market_session_date"] == "2026-09-03"
    assert quote.to_wire_patch(diff)["_market_session_date"] == "2026-09-03"


def test_reference_only_quote_has_no_fresh_trade_timestamp():
    state = MarketState()
    quote, _ = state.apply_reference_metadata(
        "HPG", session_date="2026-09-02", reference_price=22_200,
    )

    assert quote.received_timestamp == 0
    assert quote.reference_timestamp is not None


def test_new_session_book_tick_clears_all_prior_intraday_state_before_reference_refresh():
    state = MarketState()
    state.apply_reference_metadata(
        "HPG", session_date="2026-09-02", reference_price=22_200,
        ceiling_price=23_750, floor_price=20_650,
    )
    state.apply_trade_event({
        "Ticker": "HPG",
        "TradingDate": "2026-09-02T14:59:59+07:00",
        "Timestamp": "2026-09-02T14:59:59+07:00",
        "Close": 22_100,
        "Open": 22_250,
        "High": 22_350,
        "Low": 22_050,
        "Change": -100,
        "ChangePercent": -0.0045,
        "TotalVolume": 17_126_700,
        "TotalValue": 378_000_000_000,
        "MatchVolume": 1_000,
    })
    state.apply_bidask_event({
        "Ticker": "HPG",
        "Timestamp": "2026-09-02T14:59:59+07:00",
        "Best1Bid": 22_050,
        "Best1BidVolume": 10_000,
        "Best1Ask": 22_100,
        "Best1AskVolume": 20_000,
        "Best2Bid": 22_000,
        "Best2BidVolume": 30_000,
    })

    quote, diff = state.apply_bidask_event({
        "Ticker": "HPG",
        "Timestamp": "2026-09-03T09:00:01+07:00",
        "Best1Bid": 22_300,
        "Best1BidVolume": 2_000,
        "Best1Ask": 22_400,
        "Best1AskVolume": 3_000,
    })

    assert quote.market_session_date == "2026-09-03"
    assert quote.last_price is None
    assert quote.open_price is None
    assert quote.high_price is None
    assert quote.low_price is None
    assert quote.total_volume is None
    assert quote.trading_value is None
    assert quote.traded_quantity is None
    assert quote.bid1_price == 22_300
    assert quote.ask1_price == 22_400
    assert quote.bid2_price is None
    assert diff["last_price"] is None
    assert diff["total_volume"] is None
    assert diff["bid2_price"] is None

    quote, ref_diff = state.apply_reference_metadata(
        "HPG", session_date="2026-09-03", reference_price=22_200,
        ceiling_price=23_750, floor_price=20_650,
    )
    assert quote.last_price is None
    assert quote.price_change is None
    assert quote.price_change_percent is None
    assert "price_change" not in ref_diff
    assert "price_change_percent" not in ref_diff


def test_delayed_prior_session_event_cannot_roll_state_backward():
    state = MarketState()
    current, _ = state.apply_trade_event({
        "Ticker": "HPG",
        "Timestamp": "2026-09-03T09:01:00+07:00",
        "Close": 22_500,
        "TotalVolume": 5_000,
    })

    quote, diff = state.apply_trade_event({
        "Ticker": "HPG",
        "Timestamp": "2026-09-02T14:59:59+07:00",
        "Close": 22_100,
        "TotalVolume": 17_126_700,
    })

    assert diff == {}
    assert quote.last_price == current.last_price == 22_500
    assert quote.total_volume == current.total_volume == 5_000
    assert quote.market_session_date == "2026-09-03"
