"""The nightly warm pass: when it runs.

It was a closure inside `lifespan` that no test reached, and it raised NameError on every
tick in production from the day it shipped - `market_session` was imported only inside a
different function. These drive `DailyBarWarmer.tick` directly; the last one does so with
the real clock, which is the test that would have caught it.
"""

from datetime import datetime

import pytest

from app.core.config import settings
from app.market_data.history_warm import MAX_ATTEMPTS_PER_SESSION, DailyBarWarmer
from app.market_data.trading_calendar import _as_vn

pytestmark = pytest.mark.asyncio


class _Clock:
    def __init__(self) -> None:
        self.now = _as_vn(datetime(2026, 9, 29, 16, 5))
        self.trading = False
        self.session = "2026-09-29"


def _warmer(clock: _Clock, calls: list, *, fail: int = 0, universe=("HPG", "CHPG2618")):
    remaining = {"fail": fail}

    async def warm(symbols):
        calls.append(list(symbols))
        if remaining["fail"]:
            remaining["fail"] -= 1
            raise RuntimeError("database unavailable")
        return {"requested": len(symbols)}

    return DailyBarWarmer(
        warm=warm,
        universe=lambda: list(universe),
        now_vn=lambda: clock.now,
        trading_active=lambda: clock.trading,
        session_date=lambda: clock.session,
    )


@pytest.fixture(autouse=True)
def _enabled(monkeypatch):
    monkeypatch.setattr(settings, "HISTORY_NIGHTLY_WARM_ENABLED", True)
    monkeypatch.setattr(settings, "HISTORY_NIGHTLY_WARM_HOUR_ICT", 16)


async def test_it_runs_after_the_close_over_the_universe():
    clock, calls = _Clock(), []
    assert await _warmer(clock, calls).tick() == {"requested": 2}
    assert calls == [["HPG", "CHPG2618"]]


async def test_it_waits_for_the_warm_hour():
    clock, calls = _Clock(), []
    clock.now = _as_vn(datetime(2026, 9, 29, 15, 30))
    assert await _warmer(clock, calls).tick() is None
    assert calls == []


async def test_it_never_competes_with_the_live_session():
    clock, calls = _Clock(), []
    clock.trading = True
    assert await _warmer(clock, calls).tick() is None
    assert calls == []


async def test_it_runs_once_per_session_and_again_the_next():
    clock, calls = _Clock(), []
    warmer = _warmer(clock, calls)
    await warmer.tick()
    await warmer.tick()
    assert len(calls) == 1
    clock.session, clock.now = "2026-09-30", _as_vn(datetime(2026, 9, 30, 16, 5))
    await warmer.tick()
    assert len(calls) == 2


async def test_a_failed_pass_is_retried_not_written_off():
    """The old loop marked the session warmed BEFORE running, so one failure cost the night."""
    clock, calls = _Clock(), []
    warmer = _warmer(clock, calls, fail=1)
    with pytest.raises(RuntimeError):
        await warmer.tick()
    assert warmer.warmed_session is None
    assert await warmer.tick() == {"requested": 2}
    assert warmer.warmed_session == "2026-09-29"


async def test_retries_stop_after_a_few_attempts_in_one_session():
    clock, calls = _Clock(), []
    warmer = _warmer(clock, calls, fail=99)
    for _ in range(MAX_ATTEMPTS_PER_SESSION + 3):
        try:
            await warmer.tick()
        except RuntimeError:
            pass
    assert len(calls) == MAX_ATTEMPTS_PER_SESSION


async def test_it_does_nothing_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "HISTORY_NIGHTLY_WARM_ENABLED", False)
    clock, calls = _Clock(), []
    assert await _warmer(clock, calls).tick() is None
    assert calls == []


async def test_an_empty_universe_is_not_a_pass():
    clock, calls = _Clock(), []
    assert await _warmer(clock, calls, universe=()).tick() is None
    assert calls == []


async def test_the_default_clock_and_calendar_are_the_real_ones():
    """No injected clock: every default dependency is called for real. The production loop
    never got this far - it died on its first line."""
    calls = []

    async def warm(symbols):
        calls.append(symbols)
        return {}

    warmer = DailyBarWarmer(warm=warm, universe=lambda: ["HPG"])
    result = await warmer.tick()  # must not raise, whatever the time of day
    assert result in (None, {})
