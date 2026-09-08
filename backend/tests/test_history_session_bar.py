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
    bars = await svc._with_session_bar(
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
    bars = await svc._with_session_bar(
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
    assert await svc._with_session_bar(
        prior, "HPG", "5m",
        date(2026, 9, 1), date(2026, 9, 7),
        adjusted=False, price_basis="RAW",
    ) == prior


async def test_an_unknown_symbol_is_simply_left_alone(state):
    svc = HistoryReadService()
    assert await svc._with_session_bar(
        [], "NOPE", "1d",
        date(2026, 9, 1), date(2026, 9, 7),
        adjusted=False, price_basis="RAW",
    ) == []


# --------------------------------------------------------------------------- #
# Sessions the app OBSERVED itself.
#
# The live-state bar alone was not enough: market_state is deliberately cleared at the
# 08:00 ICT rollover, so a session it was the only source for vanished from the chart the
# next morning. On 2026-09-08 the HPG chart's newest candle was 2026-09-04 again, because
# 09-07 had never reached market_bars (the provider entitlement had lapsed) and the live
# state that had been serving it was wiped at 08:00. The snapshot store still held it.
# --------------------------------------------------------------------------- #
class _Snap:
    def __init__(self, day, o, h, l, c, v, value=None):
        self.session_date = date.fromisoformat(day)
        self.open_price, self.high_price, self.low_price = o, h, l
        self.last_price, self.total_volume, self.trading_value = c, v, value


@pytest.fixture
def snapshots(monkeypatch):
    store: dict[str, list] = {}

    async def fake(self, symbol, req_from, req_to, *, adjusted, price_basis):
        from app.market_data.market_schemas import HistoricalBar as HB

        out = []
        for s in store.get(symbol.upper(), []):
            if not (req_from <= s.session_date <= req_to):
                continue
            if any(x is None or x <= 0 for x in (s.open_price, s.high_price, s.low_price, s.last_price)):
                continue
            if s.total_volume is None or s.total_volume <= 0:
                continue
            d = s.session_date.isoformat()
            out.append(HB(date=d, open=s.open_price, high=s.high_price, low=s.low_price,
                          close=s.last_price, volume=s.total_volume, value=s.trading_value,
                          price_basis=price_basis, adjusted=adjusted,
                          source="OBSERVED_SESSION", session_date=d))
        return out

    monkeypatch.setattr(HistoryReadService, "_observed_session_bars", fake)
    return store


async def test_a_session_only_the_app_saw_survives_the_0800_rollover(state, snapshots):
    """The reported symptom: after 08:00 on 09-08 the chart's newest candle was 09-04 and
    the whole of 09-07 - which the terminal had displayed all day - was gone."""
    snapshots["HPG"] = [_Snap("2026-09-07", 21_800, 22_150, 21_550, 21_550, 19_957_800)]
    svc = HistoryReadService()
    bars = await svc._with_session_bar(
        [_completed("2026-09-03", 21_600.0), _completed("2026-09-04", 21_700.0)],
        "HPG", "1d", date(2026, 9, 1), date(2026, 9, 8),
        adjusted=False, price_basis="RAW",
    )
    assert [b.date for b in bars] == ["2026-09-03", "2026-09-04", "2026-09-07"]
    assert bars[-1].close == 21_550
    assert bars[-1].volume == 19_957_800
    assert bars[-1].source == "OBSERVED_SESSION"   # not passed off as the exchange's bar


async def test_an_ingested_bar_outranks_what_this_server_happened_to_see(state, snapshots):
    """Once the session is ingested the exchange's own bar is the authority."""
    snapshots["HPG"] = [_Snap("2026-09-07", 21_800, 22_150, 21_550, 21_550, 19_957_800)]
    svc = HistoryReadService()
    official = _completed("2026-09-07", 21_560.0)
    bars = await svc._with_session_bar(
        [official], "HPG", "1d", date(2026, 9, 1), date(2026, 9, 8),
        adjusted=False, price_basis="RAW",
    )
    assert bars == [official]


async def test_the_running_session_still_wins_over_a_snapshot_of_itself(state, snapshots):
    """Mid-session the live state is fresher than the last checkpoint written for it."""
    state["HPG"] = _quote()                                     # session 2026-09-07
    snapshots["HPG"] = [_Snap("2026-09-07", 21_800, 22_000, 21_600, 21_600, 12_000_000)]
    svc = HistoryReadService()
    bars = await svc._with_session_bar(
        [], "HPG", "1d", date(2026, 9, 1), date(2026, 9, 8),
        adjusted=False, price_basis="RAW",
    )
    assert len(bars) == 1
    assert bars[0].source == "REALTIME_SESSION"   # live, not the checkpoint of itself
    assert bars[0].close == 21_550                # the running close, not the stale 21,600


async def test_a_snapshot_missing_ohlcv_is_a_gap_not_a_flat_candle(state, snapshots):
    snapshots["HPG"] = [_Snap("2026-09-07", None, None, None, 21_550, 0)]
    svc = HistoryReadService()
    prior = [_completed("2026-09-04", 21_700.0)]
    assert await svc._with_session_bar(
        prior, "HPG", "1d", date(2026, 9, 1), date(2026, 9, 8),
        adjusted=False, price_basis="RAW",
    ) == prior


async def test_snapshots_outside_the_window_are_not_pulled_in(state, snapshots):
    snapshots["HPG"] = [_Snap("2026-08-14", 21_000, 21_100, 20_900, 21_050, 5_000_000)]
    svc = HistoryReadService()
    prior = [_completed("2026-09-04", 21_700.0)]
    assert await svc._with_session_bar(
        prior, "HPG", "1d", date(2026, 9, 1), date(2026, 9, 8),
        adjusted=False, price_basis="RAW",
    ) == prior


# --------------------------------------------------------------------------- #
# A provider outage must not discard sessions this server already observed.
# --------------------------------------------------------------------------- #
async def test_a_provider_outage_serves_observed_sessions_instead_of_a_503(state, snapshots, monkeypatch):
    """During the 2026-09 entitlement lapse a CW chart answered `circuit breaker is OPEN
    (AUTH_FAILURE)` while the snapshot store held that session's full OHLCV."""
    from app.market_data.market_schemas import HistoricalCircuitOpenError

    snapshots["CHPG2617"] = [_Snap("2026-09-07", 430, 440, 430, 430, 62_700)]
    svc = HistoryReadService()

    async def down(*_a, **_k):
        raise HistoricalCircuitOpenError("circuit is OPEN (AUTH_FAILURE)", reason="AUTH_FAILURE")

    monkeypatch.setattr(HistoryReadService, "_provider_direct", down)
    bars = await svc._provider_direct_or_observed(
        "CHPG2617", "1D", "2026-09-01", "2026-09-08", False, "1d", date(2026, 9, 1), date(2026, 9, 8)
    )
    assert [(b.date, b.close, b.source) for b in bars] == [("2026-09-07", 430.0, "OBSERVED_SESSION")]


async def test_with_nothing_observed_the_providers_own_error_still_surfaces(state, snapshots, monkeypatch):
    """The fallback fills a gap; it never converts a real outage into a silent empty chart."""
    from app.market_data.market_schemas import HistoricalCircuitOpenError

    svc = HistoryReadService()

    async def down(*_a, **_k):
        raise HistoricalCircuitOpenError("circuit is OPEN (AUTH_FAILURE)", reason="AUTH_FAILURE")

    monkeypatch.setattr(HistoryReadService, "_provider_direct", down)
    with pytest.raises(HistoricalCircuitOpenError):
        await svc._provider_direct_or_observed(
            "NOPE", "1D", "2026-09-01", "2026-09-08", False, "1d", date(2026, 9, 1), date(2026, 9, 8)
        )


async def test_a_bad_request_is_never_masked_by_the_fallback(state, snapshots, monkeypatch):
    """A range-limit error is the caller's fault and must keep mapping to a 400."""
    from app.market_data.market_schemas import HistoricalRangeLimitError

    snapshots["HPG"] = [_Snap("2026-09-07", 21_800, 22_150, 21_550, 21_550, 19_957_800)]
    svc = HistoryReadService()

    async def bad(*_a, **_k):
        raise HistoricalRangeLimitError("exceeds upstream timeframe limit")

    monkeypatch.setattr(HistoryReadService, "_provider_direct", bad)
    with pytest.raises(HistoricalRangeLimitError):
        await svc._provider_direct_or_observed(
            "HPG", "1D", "2020-01-01", "2026-09-08", False, "1d", date(2026, 9, 1), date(2026, 9, 8)
        )
