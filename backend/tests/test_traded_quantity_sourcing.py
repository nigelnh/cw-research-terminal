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
