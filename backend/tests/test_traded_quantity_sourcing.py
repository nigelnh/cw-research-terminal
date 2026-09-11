"""TRD_AMT (last-match size) sourcing: MatchVolume first, cumulative-advance fallback."""
import pytest
from app.market_data.market_state import MarketState

pytestmark = pytest.mark.asyncio


def _store():
    return MarketState()


async def test_match_volume_is_used_when_present():
    s = _store()
    s.apply_trade_event({"Ticker": "HPG", "Close": 21900, "TotalMatchVolume": 1000, "MatchVolume": 300})
    assert s.get_quote("HPG").traded_quantity == 300


async def test_zero_match_volume_never_overwrites_a_real_size():
    """A frame with MatchVolume 0 means 'no match in this frame'. Writing it through put a
    bogus 0 in the TRD_AMT column."""
    s = _store()
    s.apply_trade_event({"Ticker": "HPG", "Close": 21900, "TotalMatchVolume": 1000, "MatchVolume": 300})
    s.apply_trade_event({"Ticker": "HPG", "Close": 21900, "TotalMatchVolume": 1000, "MatchVolume": 0})
    assert s.get_quote("HPG").traded_quantity == 300


async def test_zero_match_volume_on_a_fresh_symbol_stays_unknown_not_zero():
    s = _store()
    s.apply_trade_event({"Ticker": "HPG", "Close": 21900, "TotalMatchVolume": 0, "MatchVolume": 0})
    assert s.get_quote("HPG").traded_quantity is None


async def test_cw_without_match_volume_derives_from_the_cumulative_advance():
    """HOSE CW trade frames carry no MatchVolume; the advance in cumulative matched volume
    is the same quantity, observed rather than estimated."""
    s = _store()
    s.apply_trade_event({"Ticker": "CVPB2615", "Close": 820, "TotalMatchVolume": 850800})
    assert s.get_quote("CVPB2615").traded_quantity is None  # no baseline yet
    s.apply_trade_event({"Ticker": "CVPB2615", "Close": 820, "TotalMatchVolume": 851100})
    assert s.get_quote("CVPB2615").traded_quantity == 300


async def test_the_fallback_never_fires_when_volume_is_flat_or_goes_backwards():
    s = _store()
    s.apply_trade_event({"Ticker": "CVPB2615", "Close": 820, "TotalMatchVolume": 1000})
    s.apply_trade_event({"Ticker": "CVPB2615", "Close": 820, "TotalMatchVolume": 1000})
    assert s.get_quote("CVPB2615").traded_quantity is None
    s.apply_trade_event({"Ticker": "CVPB2615", "Close": 820, "TotalMatchVolume": 400})
    assert s.get_quote("CVPB2615").traded_quantity is None


async def test_a_real_match_volume_still_wins_over_the_fallback():
    s = _store()
    s.apply_trade_event({"Ticker": "HPG", "Close": 21900, "TotalMatchVolume": 1000})
    s.apply_trade_event({"Ticker": "HPG", "Close": 21900, "TotalMatchVolume": 9999, "MatchVolume": 200})
    assert s.get_quote("HPG").traded_quantity == 200  # not the 8999 advance


async def test_traded_quantity_is_emitted_in_the_diff_for_the_websocket():
    s = _store()
    s.apply_trade_event({"Ticker": "CVPB2615", "Close": 820, "TotalMatchVolume": 1000})
    _, diff = s.apply_trade_event({"Ticker": "CVPB2615", "Close": 820, "TotalMatchVolume": 1500})
    assert diff.get("traded_quantity") == 500


async def test_confirmed_matches_advance_trade_revision_but_replays_and_snapshots_do_not():
    s = _store()
    first = {
        "Ticker": "CVPB2615",
        "Close": 820,
        "MatchVolume": 100,
        "TotalMatchVolume": 1_000,
        "TradingDate": "2026-09-11",
        "Timestamp": "2026-09-11T10:00:00+07:00",
        "_trade_identity": "SSI_OBSERVED|match-1",
    }
    quote, diff = s.apply_trade_event(first)
    assert quote.trade_revision == 1
    assert diff["trade_revision"] == 1
    assert quote.to_wire_patch(diff)["_trade_revision"] == 1

    replay, replay_diff = s.apply_trade_event(first)
    assert replay.trade_revision == 1
    assert "trade_revision" not in replay_diff

    second = {
        **first,
        "Timestamp": "2026-09-11T10:00:01+07:00",
        "TotalMatchVolume": 1_100,
        "_trade_identity": "SSI_OBSERVED|match-2",
    }
    quote, diff = s.apply_trade_event(second)
    assert quote.last_price == 820
    assert quote.trade_revision == 2
    assert diff["trade_revision"] == 2

    observed_snapshot = {
        **second,
        "Timestamp": "2026-09-11T10:00:02+07:00",
        "TotalMatchVolume": 1_200,
        "_synthetic_session_snapshot": True,
    }
    quote, diff = s.apply_trade_event(observed_snapshot)
    assert quote.trade_revision == 2
    assert "trade_revision" not in diff


# --------------------------------------------------------------------------- #
# Book prices: 0 means "this side is empty", not a free order.
# --------------------------------------------------------------------------- #
async def test_zero_book_prices_are_treated_as_an_empty_side():
    """CHPG2618 / CHPG2632 / CVPB2613 rendered a literal 0 in ASK_PRC while the IV solver
    correctly refused it - the stream's 0 is a sentinel, no HOSE instrument trades at 0."""
    s = MarketState()
    s.apply_bidask_event({
        "Ticker": "CHPG2618", "Best1Bid": 280, "Best1BidVolume": 100,
        "Best1Ask": 0, "Best1AskVolume": 0,
    })
    q = s.get_quote("CHPG2618")
    assert q.bid1_price == 280
    assert q.ask1_price is None          # not 0
    assert q.bid1_quantity == 100
    assert q.ask1_quantity == 0          # a size of 0 is a real size and survives


async def test_zero_prices_are_dropped_at_every_depth_level():
    s = MarketState()
    s.apply_bidask_event({
        "Ticker": "CVPB2613",
        "Best1Bid": 140, "Best1Ask": 0,
        "Best2Bid": 0, "Best2Ask": 0,
        "Best3Bid": 0, "Best3Ask": 0,
    })
    q = s.get_quote("CVPB2613")
    assert q.bid1_price == 140
    for field in ("ask1_price", "bid2_price", "ask2_price", "bid3_price", "ask3_price"):
        assert getattr(q, field) is None, f"{field} should be empty, not 0"


async def test_a_real_book_price_is_untouched():
    s = MarketState()
    s.apply_bidask_event({
        "Ticker": "HPG", "Best1Bid": 21_850, "Best1Ask": 21_900,
        "Best2Bid": 21_800, "Best2Ask": 21_950,
    })
    q = s.get_quote("HPG")
    assert (q.bid1_price, q.ask1_price) == (21_850, 21_900)
    assert (q.bid2_price, q.ask2_price) == (21_800, 21_950)
