"""The nightly warm pass: when it runs, and over what.

It was a closure inside `lifespan` that no test reached, and it raised NameError on every
tick in production from the day it shipped - `market_session` was imported only inside a
different function. When it finally ran (2026-09-29, 22:34 ICT) the universe had come up on
its 30-symbol fallback: it warmed those 30, marked the session done, and never saw the 328
warrants that loaded later. These drive `DailyBarWarmer.tick` directly; the last one does so
with the real clock, which is the test that would have caught the NameError.
"""

from datetime import datetime

import pytest

from app.core.config import settings
from app.market_data.history_warm import MAX_FAILURES_PER_SESSION, DailyBarWarmer

pytestmark = pytest.mark.asyncio


class _World:
    def __init__(self) -> None:
        self.now = datetime(2026, 9, 29, 16, 5)
        self.trading = False
        self.session = "2026-09-29"
        self.universe = ["HPG", "CHPG2618"]


def _warmer(world: _World, calls: list, *, fail: int = 0):
    remaining = {"fail": fail}

    async def warm(symbols):
        calls.append(list(symbols))
        if remaining["fail"]:
            remaining["fail"] -= 1
            raise RuntimeError("database unavailable")
        return {"requested": len(symbols)}

    return DailyBarWarmer(
        warm=warm,
        universe=lambda: list(world.universe),
        now_vn=lambda: world.now,
        trading_active=lambda: world.trading,
        session_date=lambda: world.session,
    )


@pytest.fixture(autouse=True)
def _enabled(monkeypatch):
    monkeypatch.setattr(settings, "HISTORY_NIGHTLY_WARM_ENABLED", True)
    monkeypatch.setattr(settings, "HISTORY_NIGHTLY_WARM_HOUR_ICT", 16)


async def test_it_runs_after_the_close_over_the_universe():
    world, calls = _World(), []
    assert await _warmer(world, calls).tick() == {"requested": 2}
    assert calls == [["HPG", "CHPG2618"]]


@pytest.mark.parametrize("hour", [9, 12, 15])
async def test_it_waits_for_the_warm_hour(hour):
    world, calls = _World(), []
    world.now = datetime(2026, 9, 29, hour, 30)
    assert await _warmer(world, calls).tick() is None
    assert calls == []


async def test_it_still_runs_after_midnight():
    """A process restarted at 00:30 used to wait until 16:00 the next day to warm."""
    world, calls = _World(), []
    world.now = datetime(2026, 9, 30, 0, 30)
    assert await _warmer(world, calls).tick() == {"requested": 2}


async def test_the_window_closes_at_the_morning_rollover():
    world, calls = _World(), []
    world.now = datetime(2026, 9, 30, 8, 10)
    assert await _warmer(world, calls).tick() is None


async def test_it_never_competes_with_the_live_session():
    world, calls = _World(), []
    world.trading = True
    assert await _warmer(world, calls).tick() is None
    assert calls == []


async def test_a_warmed_universe_is_not_warmed_twice_in_a_session():
    world, calls = _World(), []
    warmer = _warmer(world, calls)
    await warmer.tick()
    assert await warmer.tick() is None
    assert len(calls) == 1
    world.session, world.now = "2026-09-30", datetime(2026, 9, 30, 16, 5)
    await warmer.tick()
    assert calls[-1] == ["HPG", "CHPG2618"], "a new session warms everything again"


async def test_symbols_that_join_the_universe_later_are_warmed_then():
    """The 2026-09-29 failure: a 30-symbol fallback warmed and marked done, 328 never seen."""
    world, calls = _World(), []
    warmer = _warmer(world, calls)
    world.universe = ["HPG"]
    await warmer.tick()
    world.universe = ["HPG", "CHPG2618", "CHPG2627"]
    assert await warmer.tick() == {"requested": 2}
    assert calls == [["HPG"], ["CHPG2618", "CHPG2627"]]
    assert warmer.warmed_symbols("2026-09-29") == {"HPG", "CHPG2618", "CHPG2627"}


async def test_a_failed_pass_is_retried_not_written_off():
    world, calls = _World(), []
    warmer = _warmer(world, calls, fail=1)
    with pytest.raises(RuntimeError):
        await warmer.tick()
    assert warmer.warmed_symbols("2026-09-29") == set()
    assert await warmer.tick() == {"requested": 2}
    assert warmer.warmed_symbols("2026-09-29") == {"HPG", "CHPG2618"}


async def test_failures_stop_after_a_few_in_one_session():
    world, calls = _World(), []
    warmer = _warmer(world, calls, fail=99)
    for _ in range(MAX_FAILURES_PER_SESSION + 3):
        try:
            await warmer.tick()
        except RuntimeError:
            pass
    assert len(calls) == MAX_FAILURES_PER_SESSION


async def test_progress_does_not_count_against_the_failure_cap():
    world, calls = _World(), []
    warmer = _warmer(world, calls)
    for i in range(MAX_FAILURES_PER_SESSION + 2):
        world.universe = [f"S{j}" for j in range(i + 1)]
        await warmer.tick()
    assert len(calls) == MAX_FAILURES_PER_SESSION + 2


async def test_it_does_nothing_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "HISTORY_NIGHTLY_WARM_ENABLED", False)
    world, calls = _World(), []
    assert await _warmer(world, calls).tick() is None
    assert calls == []


async def test_an_empty_universe_is_not_a_pass():
    world, calls = _World(), []
    world.universe = []
    assert await _warmer(world, calls).tick() is None
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
