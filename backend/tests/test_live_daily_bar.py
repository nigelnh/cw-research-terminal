"""Today's forming 1D candle.

The instrument panel charts daily bars, but only the intraday timeframes had a live
bucket - so the newest candle stayed yesterday's completed bar while the header showed a
live price (HPG: chart close 21,700 vs TRD_PRC 21,900).
"""
import pytest

from app.market_data.live_bar_builder import LiveBarBuilder

pytestmark = pytest.mark.asyncio


def _daily(patches):
    return next((p["bar"] for p in patches if p["timeframe"] == "1D"), None)


def _tick(**over):
    base = {
        "Ticker": "HPG", "TradingDate": "2026-09-07T09:20:00+07:00",
        "Close": 21_900, "Open": 21_750, "High": 21_950, "Low": 21_600,
        "MatchVolume": 300, "TotalMatchVolume": 9_278_800, "TotalMatchValue": 202_000_000_000,
    }
    base.update(over)
    return base


async def test_a_daily_patch_is_emitted_alongside_the_intraday_ones():
    b = LiveBarBuilder()
    patches = b.on_trade("HPG", _tick())
    frames = {p["timeframe"] for p in patches}
    assert "1D" in frames
    assert {"1m", "5m", "15m", "30m", "1h"} <= frames


async def test_the_daily_bar_uses_the_session_date_so_it_replaces_todays_rest_row():
    """REST daily bars are keyed 'YYYY-MM-DD'; the chart merges on that key."""
    bar = _daily(LiveBarBuilder().on_trade("HPG", _tick()))
    assert bar["date"] == "2026-09-07"
    assert bar["session_date"] == "2026-09-07"
    assert bar["complete"] is False
    assert bar["price_basis"] == "RAW"


async def test_it_prefers_the_providers_own_session_ohlc_over_observed_ticks():
    bar = _daily(LiveBarBuilder().on_trade("HPG", _tick()))
    assert (bar["open"], bar["high"], bar["low"], bar["close"]) == (21_750, 21_950, 21_600, 21_900)


async def test_cumulative_totals_are_absolute_not_summed():
    """Session totals are already cumulative; summing them would multiply the day's volume
    and would also break after a reconnect that missed part of the session."""
    b = LiveBarBuilder()
    b.on_trade("HPG", _tick())
    bar = _daily(b.on_trade("HPG", _tick(
        TradingDate="2026-09-07T09:21:00+07:00", Close=21_950, TotalMatchVolume=9_300_000,
        TotalMatchValue=203_000_000_000,
    )))
    assert bar["volume"] == 9_300_000
    assert bar["value"] == 203_000_000_000
    assert bar["close"] == 21_950


async def test_a_frame_without_session_ohlc_falls_back_to_the_observed_trades():
    b = LiveBarBuilder()
    b.on_trade("CHPG2627", {
        "Ticker": "CHPG2627", "TradingDate": "2026-09-07T09:20:00+07:00", "Close": 1_100,
    })
    bar = _daily(b.on_trade("CHPG2627", {
        "Ticker": "CHPG2627", "TradingDate": "2026-09-07T09:25:00+07:00", "Close": 1_190,
    }))
    assert bar["open"] == 1_100
    assert bar["high"] == 1_190
    assert bar["low"] == 1_100
    assert bar["close"] == 1_190


async def test_a_new_session_starts_a_new_daily_candle():
    b = LiveBarBuilder()
    b.on_trade("HPG", _tick())
    bar = _daily(b.on_trade("HPG", _tick(
        TradingDate="2026-09-08T09:16:00+07:00", Close=22_000,
        Open=21_900, High=22_050, Low=21_880, TotalMatchVolume=120_000,
    )))
    assert bar["date"] == "2026-09-08"
    assert bar["open"] == 21_900
    assert bar["volume"] == 120_000


async def test_a_zero_or_missing_price_still_produces_nothing():
    b = LiveBarBuilder()
    assert b.on_trade("HPG", _tick(Close=0)) == []
    assert b.on_trade("HPG", {"Ticker": "HPG", "TradingDate": "2026-09-07T09:20:00+07:00"}) == []
