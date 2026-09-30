"""The ingestion cursor records a day as answered only once the day has settled.

FiinQuant once published a session's final daily bar hours after the close. A probe that
raced it stamped the cursor past the day anyway, and the day was never asked for again -
the reason every missing day of the last five used to be re-asked on every fill, which is
also what re-asked every thin warrant's non-trading days every night. Now the cursor waits
instead: a probe before the bar can be out leaves the day open; one after it closes it.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

import app.persistence.ingestion.service as service_module
from app.core.config import settings
from app.market_data.market_schemas import HistoricalNoDataError
from app.persistence.ingestion.trading_calendar import (
    expected_trading_days,
    last_completed_session_date,
)
from app.persistence.market_time import VN_TZ

from .test_history_read import _insert_bars, _seed_instrument, _set_cursor

pytestmark = pytest.mark.asyncio


async def test_a_day_asked_for_before_it_settled_is_asked_again_after(
    ingestion_service, fake_provider, monkeypatch
):
    monkeypatch.setattr(settings, "HISTORY_BAR_SETTLE_MINUTES", 60)
    day = last_completed_session_date()  # a real session on the real calendar
    clock = {"now": datetime(day.year, day.month, day.day, 15, 20, tzinfo=VN_TZ)}
    monkeypatch.setattr(service_module, "_vn_now", lambda: clock["now"])
    iid = await _seed_instrument("CHDB2613", "CW")
    fake_provider.fail_symbol["CHDB2613"] = HistoricalNoDataError("nothing for this window")
    frm = day - timedelta(days=10)

    async def probe():
        return await ingestion_service.fill_range(
            "CHDB2613", timeframe="1d", price_basis="RAW", from_date=frm, to_date=day,
        )

    async def ceiling():
        state = await ingestion_service.get_stream_state(
            instrument_id=iid, timeframe="1d", price_basis="RAW"
        )
        return state.last_bar_ts.astimezone(VN_TZ).date()

    assert (await probe()).status == "NO_DATA"
    assert await ceiling() < day, "at 15:20 the day's bar may simply not be out yet"

    clock["now"] = clock["now"].replace(hour=16, minute=30)
    fake_provider.calls.clear()
    assert (await probe()).status == "NO_DATA"
    assert len(fake_provider.calls) == 1, "asked again once the day settled"
    assert await ceiling() == day

    fake_provider.calls.clear()
    assert (await probe()).status == "ALREADY_COVERED"
    assert fake_provider.calls == []


async def test_a_bar_that_is_already_out_is_kept_whatever_the_hour(ingestion_service, fake_provider, monkeypatch):
    """The cap only holds back the empty tail: a bar the provider did return is stored and
    moves the cursor to itself, settled or not."""
    monkeypatch.setattr(settings, "HISTORY_BAR_SETTLE_MINUTES", 60)
    day = last_completed_session_date()
    monkeypatch.setattr(
        service_module, "_vn_now", lambda: datetime(day.year, day.month, day.day, 15, 5, tzinfo=VN_TZ)
    )
    iid = await _seed_instrument("CHPG2618", "CW")
    fake_provider.seed_daily("CHPG2618", day - timedelta(days=10), day, adjusted=False)

    outcome = await ingestion_service.fill_range(
        "CHPG2618", timeframe="1d", price_basis="RAW", from_date=day - timedelta(days=10), to_date=day,
    )
    assert outcome.status == "FILLED"
    state = await ingestion_service.get_stream_state(instrument_id=iid, timeframe="1d", price_basis="RAW")
    assert state.last_bar_ts.astimezone(VN_TZ).date() == day


async def test_chart_loads_before_the_day_settles_do_not_each_ask_again(history_service, fake_provider, monkeypatch):
    """Between the close and the settle time an empty answer cannot enter the cursor, so
    the cooldown is what stops every chart load from asking the provider again."""
    monkeypatch.setattr(settings, "HISTORY_BAR_SETTLE_MINUTES", 60)
    day = last_completed_session_date()
    monkeypatch.setattr(
        service_module, "_vn_now", lambda: datetime(day.year, day.month, day.day, 15, 20, tzinfo=VN_TZ)
    )
    lo = day - timedelta(days=30)
    sessions = expected_trading_days(lo, day)
    iid = await _seed_instrument("CHDB2613", "CW")
    await _insert_bars(iid, sessions[:-1], price_basis="RAW")
    await _set_cursor(iid, lo, sessions[-2], price_basis="RAW")
    fake_provider.fail_symbol["CHDB2613"] = HistoricalNoDataError("not traded")

    async def load():
        await history_service.get_history(
            "CHDB2613", timeframe="1D", from_date=lo.isoformat(), to_date=day.isoformat(), adjusted=False,
        )

    await load()
    assert len(fake_provider.calls) == 1
    fake_provider.calls.clear()
    await load()
    assert fake_provider.calls == []
