"""
LiveQuantEngine realtime scheduling: latest-wins, single-flight, bounded tasks, lifecycle.

Every test forces a specific ordering deterministically (gated computes, controlled
tick bursts). No wall-clock ordering assumptions, no sleeps as correctness proofs.

The production quant math is unchanged and separately verified; Test G proves the
scheduling wrapper produces byte-identical analytics to a direct compute.
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.quant.quant_engine import LiveQuantEngine
from app.quant.quant_schemas import WarrantAnalytics, GreeksVolatilitySource
from app.quant.historical_volatility_service import HistoricalVolatilityService
from app.instruments.instrument_registry import instrument_registry
from app.instruments.instrument_schemas import (
    CoveredWarrantSpecification,
    InstrumentLifecycleStatus,
    DataQualityStatus,
    LifecycleEvidenceLevel,
    MetadataVerificationStatus,
)
from app.market_data.market_schemas import CanonicalQuote
from tests.fixtures.fake_bar_source import FakeBarSource, make_daily_bars, synthetic_closes

pytestmark = pytest.mark.asyncio


def _probe(sym: str, generation: int, tag: float) -> WarrantAnalytics:
    """Deterministic analytics tagged with the generation (calculated_at) and market
    state version (moneyness) so tests can assert which state won."""
    return WarrantAnalytics(
        symbol=sym,
        underlying_symbol="U",
        calculated_at=str(generation),
        is_available=True,
        moneyness=float(tag),
    )


class _HarnessEngine(LiveQuantEngine):
    """Instrumented, gate-able double. ``_compute_for_symbol`` is fully replaced."""

    def __init__(self) -> None:
        super().__init__()
        self.set_market_state_getter(lambda s: None)     # so _schedule_recompute does not early-return
        self.compute_log: list[tuple[str, int]] = []
        self.publish_log: list[tuple[str, int]] = []
        self.gates_by_gen: dict[tuple[str, int], asyncio.Event] = {}
        self.gates_by_symbol: dict[str, asyncio.Event] = {}
        self.fail_gens: set[tuple[str, int]] = set()
        self.state_tag: dict[str, float] = {}
        self._concurrent_now = 0
        self.max_concurrent_seen = 0
        self.extra_delay = 0.0

    def reset_logs(self) -> None:
        self.compute_log.clear()
        self.publish_log.clear()

    async def _compute_for_symbol(self, cw_sym: str, generation: int) -> WarrantAnalytics:
        self.compute_log.append((cw_sym, generation))
        self._concurrent_now += 1
        self.max_concurrent_seen = max(self.max_concurrent_seen, self._concurrent_now)
        try:
            key = (cw_sym, generation)
            if key in self.gates_by_gen:
                await self.gates_by_gen[key].wait()
            elif cw_sym in self.gates_by_symbol:
                await self.gates_by_symbol[cw_sym].wait()
            elif self.extra_delay:
                await asyncio.sleep(self.extra_delay)
            if key in self.fail_gens:
                raise RuntimeError(f"forced compute failure {key}")
            return _probe(cw_sym, generation, self.state_tag.get(cw_sym, 0.0))
        finally:
            self._concurrent_now -= 1

    def _publish(self, cw_sym: str, generation: int, analytics: WarrantAnalytics) -> None:
        before = self._counters["published"]
        super()._publish(cw_sym, generation, analytics)
        if self._counters["published"] > before:
            self.publish_log.append((cw_sym, generation))


async def _drain(eng: LiveQuantEngine, timeout: float = 3.0) -> None:
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        s = eng.stats()
        if s["pending_symbols"] == 0 and s["inflight_workers"] == 0 and s["tracked_tasks"] == 0:
            return
        await asyncio.sleep(0.005)
    raise AssertionError(f"engine did not drain within {timeout}s: {eng.stats()}")


async def _wait_for(pred, timeout: float = 2.0) -> None:
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if pred():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("condition not met in time")


def _watch(eng: _HarnessEngine, *cws: str, underlying: str = "U") -> None:
    """White-box registration without the auto-schedule, for precise generation control."""
    eng._watched_cw_symbols.update(cws)
    eng._underlying_to_cw_map.setdefault(underlying, set()).update(cws)


def _got(eng: LiveQuantEngine, sym: str) -> WarrantAnalytics:
    a = eng.get_analytics(sym)
    assert a is not None, f"no cached analytics for {sym}"
    return a


# --------------------------------------------------------------------------- #
# Test A - an older-state computation never becomes the final result
# --------------------------------------------------------------------------- #
async def test_A_older_state_never_wins_over_newer():
    eng = _HarnessEngine()
    broadcasts: list[tuple[str, str]] = []
    eng.set_broadcaster(lambda s, a: broadcasts.append((s, a.calculated_at)))
    _watch(eng, "C1")

    g1 = asyncio.Event()
    eng.gates_by_gen[("C1", 1)] = g1

    eng.state_tag["C1"] = 100.0
    eng.notify_market_tick("C1")                       # generation 1 - worker starts, blocks in compute
    await _wait_for(lambda: ("C1", 1) in eng.compute_log)
    assert eng.stats()["inflight_workers"] == 1

    for tag in (200.0, 300.0, 400.0, 500.0):           # burst while gen 1 is stuck
        eng.state_tag["C1"] = tag
        eng.notify_market_tick("C1")                   # generations 2,3,4,5 -> coalesced to pending=5
    assert eng.stats()["inflight_workers"] == 1        # STILL one worker
    assert eng.stats()["tracked_tasks"] == 1

    g1.set()                                           # release the stale (generation 1) computation
    await _drain(eng)

    a = eng.get_analytics("C1")
    assert a is not None
    assert a.calculated_at == "5"                      # newest generation won
    assert a.moneyness == 500.0                        # newest market-state tag won
    assert eng._cache_generation["C1"] == 5

    # generation 1 published, THEN generation 5 - never the reverse, never a regression
    assert eng.publish_log == [("C1", 1), ("C1", 5)]
    assert broadcasts == [("C1", "1"), ("C1", "5")]
    assert sorted(g for _s, g in eng.compute_log) == [1, 5]      # 2,3,4 coalesced away
    assert eng._counters["stale_discarded"] == 0
    assert eng._counters["coalesced"] >= 3
    await eng.shutdown()


async def test_A2_publish_generation_guard_rejects_strictly_older():
    """The last-line-of-defence: even if two computations for one symbol ever completed
    out of order, the generation guard prevents the older result from landing."""
    eng = _HarnessEngine()
    a5 = _probe("C1", 5, 500.0)
    a3 = _probe("C1", 3, 300.0)

    eng._publish("C1", 5, a5)
    assert eng.get_analytics("C1") is a5 and eng._cache_generation["C1"] == 5

    eng._publish("C1", 3, a3)                          # stale straggler arrives late
    assert eng.get_analytics("C1") is a5               # NOT overwritten
    assert eng._cache_generation["C1"] == 5
    assert eng._counters["stale_discarded"] == 1
    await eng.shutdown()


# --------------------------------------------------------------------------- #
# Test B - a tick burst is coalesced; task count stays bounded
# --------------------------------------------------------------------------- #
async def test_B_burst_is_coalesced_and_bounded():
    eng = _HarnessEngine()
    eng.extra_delay = 0.004
    _watch(eng, "C1")

    for i in range(200):
        eng.state_tag["C1"] = float(i)
        eng.notify_market_tick("C1")
        assert eng.stats()["inflight_workers"] <= 1
        assert eng.stats()["tracked_tasks"] <= 1
        if i % 8 == 0:
            await asyncio.sleep(0.003)                 # let the worker make progress

    await _drain(eng)

    assert _got(eng, "C1").moneyness == 199.0          # latest state computed
    assert eng._cache_generation["C1"] == eng._generation
    assert eng._counters["computed"] < 60                      # far fewer than 200
    assert eng._counters["coalesced"] > 120
    assert eng._counters["stale_discarded"] == 0
    await eng.shutdown()


async def test_B2_pending_never_holds_more_than_one_generation_per_symbol():
    eng = _HarnessEngine()
    eng.gates_by_symbol["C1"] = asyncio.Event()
    _watch(eng, "C1")
    for _ in range(50):
        eng.notify_market_tick("C1")
    assert len(eng._pending) == 1                              # one entry, not 50
    assert eng._pending["C1"] == eng._generation               # the newest
    eng.gates_by_symbol["C1"].set()
    await _drain(eng)
    await eng.shutdown()


# --------------------------------------------------------------------------- #
# Test C - a slow symbol does not block a fast, unrelated symbol
# --------------------------------------------------------------------------- #
async def test_C_slow_symbol_does_not_block_fast_symbol():
    eng = _HarnessEngine()
    _watch(eng, "CSLOW", "CFAST")

    eng.gates_by_symbol["CSLOW"] = asyncio.Event()
    eng.state_tag["CSLOW"] = 1.0
    eng.state_tag["CFAST"] = 2.0

    eng.notify_market_tick("CSLOW")                    # worker blocks in compute
    eng.notify_market_tick("CFAST")                    # independent worker, must run freely

    await _wait_for(lambda: eng.get_analytics("CFAST") is not None)
    assert _got(eng, "CFAST").moneyness == 2.0
    assert eng.get_analytics("CSLOW") is None          # still blocked
    assert ("CSLOW", 1) in eng.compute_log             # it did start

    eng.gates_by_symbol["CSLOW"].set()
    await _drain(eng)
    assert _got(eng, "CSLOW").moneyness == 1.0
    await eng.shutdown()


# --------------------------------------------------------------------------- #
# Test D - one underlying tick fans out to several CWs, bounded, each latest-wins
# --------------------------------------------------------------------------- #
async def test_D_underlying_fanout_bounded_and_each_cw_latest_wins():
    eng = _HarnessEngine()
    eng._compute_sem = asyncio.Semaphore(2)            # force the global bound to bite
    eng.extra_delay = 0.006
    cws = ["C1", "C2", "C3", "C4", "C5"]
    _watch(eng, *cws, underlying="HPG")

    for c in cws:
        eng.state_tag[c] = 10.0
    eng.notify_market_tick("HPG")                      # fan-out: 5 workers
    assert eng.stats()["inflight_workers"] == 5
    assert eng.stats()["tracked_tasks"] == 5

    for c in cws:                                      # a newer underlying tick mid-flight
        eng.state_tag[c] = 20.0
    eng.notify_market_tick("HPG")

    await _drain(eng)

    for c in cws:
        a = eng.get_analytics(c)
        assert a is not None and a.moneyness == 20.0   # every CW ends at the newest state
    assert eng.max_concurrent_seen <= 2                # global concurrency bound respected
    assert eng._counters["stale_discarded"] == 0
    await eng.shutdown()


async def test_D2_unrelated_underlying_tick_does_not_touch_other_cws():
    eng = _HarnessEngine()
    _watch(eng, "CHPG", underlying="HPG")
    _watch(eng, "CVHM", underlying="VHM")
    eng.state_tag["CHPG"] = 1.0
    eng.state_tag["CVHM"] = 1.0

    eng.notify_market_tick("HPG")
    await _drain(eng)
    assert eng.get_analytics("CHPG") is not None
    assert eng.get_analytics("CVHM") is None           # HPG tick must not recompute CVHM
    await eng.shutdown()


# --------------------------------------------------------------------------- #
# Test E - a compute exception preserves the last good cache; the worker recovers
# --------------------------------------------------------------------------- #
async def test_E_exception_preserves_cache_and_worker_recovers():
    eng = _HarnessEngine()
    _watch(eng, "C1")

    eng.state_tag["C1"] = 10.0
    eng.notify_market_tick("C1")
    await _drain(eng)
    good = _got(eng, "C1")
    good_gen = eng._cache_generation["C1"]
    assert good.moneyness == 10.0

    eng.state_tag["C1"] = 20.0
    eng.fail_gens.add(("C1", eng._generation + 1))     # the next scheduled generation will raise
    eng.notify_market_tick("C1")
    await _drain(eng)

    assert eng.get_analytics("C1") is good             # last good analytics untouched
    assert eng._cache_generation["C1"] == good_gen     # generation not advanced
    assert eng._counters["failures"] == 1
    assert "C1" not in eng._inflight                   # NOT stuck "in flight"

    eng.state_tag["C1"] = 30.0
    eng.notify_market_tick("C1")                       # a later tick still works
    await _drain(eng)
    assert _got(eng, "C1").moneyness == 30.0
    await eng.shutdown()


async def test_E2_broadcast_exception_does_not_kill_worker_or_lose_cache():
    eng = _HarnessEngine()

    def _boom(_s, _a):
        raise RuntimeError("broadcaster down")

    eng.set_broadcaster(_boom)
    _watch(eng, "C1")
    eng.state_tag["C1"] = 5.0
    eng.notify_market_tick("C1")
    await _drain(eng)
    assert _got(eng, "C1").moneyness == 5.0    # cache written despite broadcast failure
    assert eng._counters["broadcast_errors"] == 1

    eng.state_tag["C1"] = 6.0
    eng.notify_market_tick("C1")
    await _drain(eng)
    assert _got(eng, "C1").moneyness == 6.0    # worker still healthy
    await eng.shutdown()


# --------------------------------------------------------------------------- #
# Test F - shutdown cancels in-flight work and blocks new scheduling
# --------------------------------------------------------------------------- #
async def test_F_shutdown_is_clean_and_terminal():
    eng = _HarnessEngine()
    _watch(eng, "C1")
    eng.gates_by_symbol["C1"] = asyncio.Event()        # block forever
    eng.notify_market_tick("C1")
    await _wait_for(lambda: eng.stats()["tracked_tasks"] == 1)

    await eng.shutdown()

    assert eng.stats()["tracked_tasks"] == 0
    assert eng._inflight == {}
    assert eng._pending == {}

    scheduled_before = eng._counters["scheduled"]
    eng.notify_market_tick("C1")                       # ignored after shutdown
    assert eng._counters["scheduled"] == scheduled_before
    await asyncio.sleep(0.02)
    assert eng.stats()["tracked_tasks"] == 0           # nothing spawned

    eng.startup()                                      # re-arm
    eng.gates_by_symbol.pop("C1", None)
    eng.state_tag["C1"] = 9.0
    eng.notify_market_tick("C1")
    assert eng._counters["scheduled"] == scheduled_before + 1
    await _drain(eng)
    assert _got(eng, "C1").moneyness == 9.0
    await eng.shutdown()


async def test_F2_shutdown_retrieves_task_exceptions():
    eng = _HarnessEngine()
    _watch(eng, "C1")
    eng.fail_gens.add(("C1", 1))
    eng.notify_market_tick("C1")
    await _drain(eng)                                  # failure handled inside the worker
    await eng.shutdown()
    # no "Task exception was never retrieved" and the worker survived the exception
    assert eng._counters["failures"] == 1
    assert eng.stats()["tracked_tasks"] == 0


async def test_F3_unregister_cancels_symbol_worker_and_clears_state():
    eng = _HarnessEngine()
    _watch(eng, "C1")
    eng.gates_by_symbol["C1"] = asyncio.Event()
    eng._analytics_cache["C1"] = _probe("C1", 1, 1.0)
    eng._cache_generation["C1"] = 1
    eng.notify_market_tick("C1")
    await _wait_for(lambda: "C1" in eng._inflight)

    eng.unregister_watched_cw("C1")
    await asyncio.sleep(0.02)

    assert "C1" not in eng._inflight
    assert "C1" not in eng._pending
    assert "C1" not in eng._analytics_cache
    assert "C1" not in eng._cache_generation
    assert eng.stats()["tracked_tasks"] == 0
    await eng.shutdown()


# --------------------------------------------------------------------------- #
# Test G - the scheduled path produces IDENTICAL analytics to a direct compute
# --------------------------------------------------------------------------- #
def _real_spec() -> CoveredWarrantSpecification:
    return CoveredWarrantSpecification(
        symbol="CHPG2602", issuer="TCBS", underlying_symbol="HPG",
        strike_price=25885.0, exercise_ratio=3.5704,
        maturity_date="2026-12-19", last_trading_date="2026-12-17",
        status=InstrumentLifecycleStatus.ACTIVE, data_quality=DataQualityStatus.COMPLETE,
        evidence_level=LifecycleEvidenceLevel.CURRENT_EXCHANGE_LIST,
        metadata_verification=MetadataVerificationStatus.VERIFIED_CURRENT,
    )


async def test_G_scheduled_path_matches_direct_compute_numerically():
    spec = _real_spec()
    und = CanonicalQuote(symbol="HPG", instrument_type="STOCK", last_price=26500.0)
    cw = CanonicalQuote(symbol="CHPG2602", instrument_type="CW",
                        bid1_price=1200.0, ask1_price=1250.0, last_price=1230.0)

    hv = HistoricalVolatilityService(bar_source=FakeBarSource({"HPG": make_daily_bars(synthetic_closes(40))}))
    await hv.warm(["HPG"])

    eng = LiveQuantEngine()
    eng.startup()
    eng.set_historical_vol_getter(hv.get_estimate)
    eng.set_market_state_getter(lambda s: {"CHPG2602": cw, "HPG": und}.get(s))

    from app.quant.quant_engine import get_vietnam_now
    from app.market_data.trading_calendar import reference_session_date, VN_TZ
    from datetime import datetime, time
    day = reference_session_date(get_vietnam_now())
    stamp = int(min(get_vietnam_now(), datetime.combine(day, time(15), tzinfo=VN_TZ)).timestamp() * 1000)
    for quote in (cw, und):
        quote.market_session_date = day.isoformat()
        quote.trade_timestamp = quote.book_timestamp = stamp

    # 1. direct (already-verified) path
    direct = await eng.compute_warrant_analytics("CHPG2602", spec=spec, cw_state=cw, und_state=und)

    # 2. full scheduler path
    with patch.object(instrument_registry, "get_instrument", AsyncMock(return_value=spec)):
        eng._watched_cw_symbols.add("CHPG2602")
        eng._underlying_to_cw_map["HPG"] = {"CHPG2602"}
        eng.notify_market_tick("CHPG2602")
        await _drain(eng)
        scheduled = eng.get_analytics("CHPG2602")

    assert scheduled is not None
    d, s = direct.model_dump(), scheduled.model_dump()
    d.pop("calculated_at")
    s.pop("calculated_at")
    assert s == d                                       # byte-identical analytics + Greeks + IVs
    assert scheduled.greeks.volatility_source == GreeksVolatilitySource.IV_TRADE

    # Volume/timestamp-only quote updates do not change any pricing input, so they keep
    # the exact cached object and do not make time-to-maturity drift on screen.
    with patch.object(instrument_registry, "get_instrument", AsyncMock(return_value=spec)):
        computed = eng.stats()["computed"]
        cw.total_volume = 99_000
        cw.received_timestamp = stamp + 1_000
        eng.notify_market_tick("CHPG2602")
        await _drain(eng)
        assert eng.get_analytics("CHPG2602") is scheduled
        assert eng.stats()["computed"] == computed
        assert eng.stats()["input_cache_hits"] == 1

        # A genuine new execution at the same displayed price must still bind IV_TRADE to
        # the new match revision and publish a fresh analytics snapshot.
        cw.trade_revision = 1
        cw.trade_timestamp = stamp + 2_000
        eng.notify_market_tick("CHPG2602")
        await _drain(eng)
        matched = eng.get_analytics("CHPG2602")
        assert matched is not None
        assert matched is not scheduled
        assert matched.model_inputs is not None
        assert matched.model_inputs.market_last_revision == 1
        assert eng.stats()["computed"] == computed + 1

        # A price change remains a valuation input change and schedules another calculation.
        cw.bid1_price = 1210.0
        eng.notify_market_tick("CHPG2602")
        await _drain(eng)
        assert eng.stats()["computed"] == computed + 2
    await eng.shutdown()


async def test_G2_current_price_analytics_restore_across_process_cache():
    spec = _real_spec()
    und = CanonicalQuote(symbol="HPG", instrument_type="STOCK", last_price=26500.0)
    cw = CanonicalQuote(
        symbol="CHPG2602", instrument_type="CW",
        bid1_price=1200.0, ask1_price=1250.0, last_price=1230.0,
    )
    hv = HistoricalVolatilityService(
        bar_source=FakeBarSource({"HPG": make_daily_bars(synthetic_closes(40))})
    )
    await hv.warm(["HPG"])

    from app.quant.quant_engine import get_vietnam_now
    from app.market_data.trading_calendar import reference_session_date, VN_TZ
    from datetime import datetime, time
    now = get_vietnam_now()
    day = reference_session_date(now)
    stamp = int(min(now, datetime.combine(day, time(15), tzinfo=VN_TZ)).timestamp() * 1000)
    for quote in (cw, und):
        quote.market_session_date = day.isoformat()
        quote.trade_timestamp = quote.book_timestamp = stamp

    source = LiveQuantEngine()
    source.set_historical_vol_getter(hv.get_estimate)
    source.set_market_state_getter(lambda s: {"CHPG2602": cw, "HPG": und}.get(s))
    analytics = await source.compute_warrant_analytics(
        "CHPG2602", spec=spec, cw_state=cw, und_state=und
    )

    class AnalyticsStore:
        def is_available(self):
            return True

        async def load_quant_analytics(self, symbols, session_date):
            return {
                "CHPG2602": analytics.model_dump(mode="json")
            } if session_date == day.isoformat() and "CHPG2602" in symbols else {}

    restored_engine = LiveQuantEngine()
    restored_engine.set_historical_vol_getter(hv.get_estimate)
    restored_engine.set_market_state_getter(
        lambda s: {"CHPG2602": cw, "HPG": und}.get(s)
    )
    restored_engine.set_analytics_store(AnalyticsStore())
    with patch.object(instrument_registry, "get_instrument", AsyncMock(return_value=spec)):
        assert await restored_engine.restore_analytics(["CHPG2602"], now=now) == 1
    assert restored_engine.get_analytics(
        "CHPG2602", now=now, validate_inputs=True
    ) is not None

    # A persisted result cannot cross a changed market-price boundary.
    cw.bid1_price = 1210.0
    mismatched_engine = LiveQuantEngine()
    mismatched_engine.set_historical_vol_getter(hv.get_estimate)
    mismatched_engine.set_market_state_getter(
        lambda s: {"CHPG2602": cw, "HPG": und}.get(s)
    )
    mismatched_engine.set_analytics_store(AnalyticsStore())
    with patch.object(instrument_registry, "get_instrument", AsyncMock(return_value=spec)):
        assert await mismatched_engine.restore_analytics(["CHPG2602"], now=now) == 0


# --------------------------------------------------------------------------- #
# Instrumentation
# --------------------------------------------------------------------------- #
async def test_counters_and_stats_are_coherent():
    eng = _HarnessEngine()
    _watch(eng, "C1")
    eng.extra_delay = 0.002
    for i in range(30):
        eng.state_tag["C1"] = float(i)
        eng.notify_market_tick("C1")
        if i % 5 == 0:
            await asyncio.sleep(0.003)
    await _drain(eng)
    s = eng.stats()
    assert s["scheduled"] == 30
    assert s["computed"] + s["coalesced"] >= 30
    assert s["published"] == s["computed"]             # every non-failed compute published (all newer)
    assert s["failures"] == 0
    assert s["tracked_tasks"] == 0 and s["inflight_workers"] == 0 and s["pending_symbols"] == 0
    assert s["cached_symbols"] == 1
    await eng.shutdown()
