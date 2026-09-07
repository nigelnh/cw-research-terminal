"""The current session as the newest daily bar.

Neither store of completed bars can hold today: PostgreSQL keeps sessions past their close,
and the provider's daily series stops at the last completed session. The chart used to fill
that in from WebSocket ticks in the browser, so today's candle existed only in a tab that
had watched it stream - a reload after the close, or a different machine, showed yesterday
as the newest candle while the header beside it quoted today's price.
"""
from datetime import date

import pytest

from app.market_data.history_read_service import HistoryReadService
from app.market_data.market_schemas import HistoricalBar

pytestmark = pytest.mark.asyncio


def _quote(**over):
    from app.market_data.market_schemas import CanonicalQuote

    base = dict(
        symbol="HPG", open_price=21_800.0, high_price=22_150.0, low_price=21_550.0,
        last_price=21_550.0, total_volume=19_957_800, trading_value=435_464_115_000.0,
        market_session_date="2026-09-07",
    )
    base.update(over)
    return CanonicalQuote(**base)


@pytest.fixture
def state(monkeypatch):
    from app.market_data.market_state import market_state

    store: dict = {}
    monkeypatch.setattr(market_state, "get_quote", lambda s: store.get(s.upper()))
    return store


def _completed(day: str, close: float) -> HistoricalBar:
    return HistoricalBar(
        date=day, open=close, high=close, low=close, close=close, volume=1_000.0,
        price_basis="RAW", adjusted=False, session_date=day,
    )


async def test_todays_session_is_appended_when_the_series_stops_at_yesterday(state):
    """The reported symptom: the chart's newest candle was 2026-09-04 while the panel
    beside it showed today's 21,550 close on 19.96M shares."""
    state["HPG"] = _quote()
    svc = HistoryReadService()
    bars = svc._with_session_bar(
        [_completed("2026-09-03", 21_600.0), _completed("2026-09-04", 21_700.0)],
        "HPG", "1d", date(2026, 9, 1), date(2026, 9, 7),
        adjusted=False, price_basis="RAW",
    )
    assert [b.date for b in bars] == ["2026-09-03", "2026-09-04", "2026-09-07"]
    today = bars[-1]
    assert (today.open, today.high, today.low, today.close) == (21_800.0, 22_150.0, 21_550.0, 21_550.0)
    assert today.volume == 19_957_800.0
    assert today.source == "REALTIME_SESSION"     # provenance is explicit, never "FIINQUANT"


async def test_a_persisted_bar_for_the_same_day_always_wins(state):
    """Once the session is ingested, the exchange's own bar replaces the running total."""
    state["HPG"] = _quote()
    svc = HistoryReadService()
    settled = _completed("2026-09-07", 21_500.0)
    bars = svc._with_session_bar(
        [settled], "HPG", "1d",
        date(2026, 9, 1), date(2026, 9, 7),
        adjusted=False, price_basis="RAW",
    )
    assert bars == [settled]


@pytest.mark.parametrize("missing", ["open_price", "high_price", "low_price", "last_price"])
async def test_a_partial_session_is_a_gap_not_a_part_invented_bar(state, missing):
    state["HPG"] = _quote(**{missing: None})
    svc = HistoryReadService()
    assert svc._session_bar(
        "HPG", date(2026, 9, 1), date(2026, 9, 7),
        adjusted=False, price_basis="RAW",
    ) is None


async def test_an_instrument_that_quoted_but_never_traded_gets_no_bar(state):
    """A sparsely-traded CW shows a book all day without a single match. Zero volume is not
    a candle."""
    state["CHPG2618"] = _quote(symbol="CHPG2618", total_volume=0)
    svc = HistoryReadService()
    assert svc._session_bar(
        "CHPG2618", date(2026, 9, 1), date(2026, 9, 7),
        adjusted=False, price_basis="RAW",
    ) is None


async def test_a_session_outside_the_requested_window_is_not_appended(state):
    state["HPG"] = _quote()
    svc = HistoryReadService()
    assert svc._session_bar(
        "HPG", date(2026, 1, 1), date(2026, 6, 30),
        adjusted=False, price_basis="RAW",
    ) is None


async def test_intraday_timeframes_never_get_a_synthetic_daily_bar(state):
    state["HPG"] = _quote()
    svc = HistoryReadService()
    prior = [_completed("2026-09-04T09:15:00", 21_700.0)]
    assert svc._with_session_bar(
        prior, "HPG", "5m",
        date(2026, 9, 1), date(2026, 9, 7),
        adjusted=False, price_basis="RAW",
    ) == prior


async def test_an_unknown_symbol_is_simply_left_alone(state):
    svc = HistoryReadService()
    assert svc._with_session_bar(
        [], "NOPE", "1d",
        date(2026, 9, 1), date(2026, 9, 7),
        adjusted=False, price_basis="RAW",
    ) == []
