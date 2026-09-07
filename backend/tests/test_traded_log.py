"""Time & sales tape: only real matches, an honest derived side, 08:00 ICT retention."""
import json
from datetime import datetime, timedelta

import pytest

from app.market_data.market_state import MarketState
from app.market_data.traded_log import (
    TradedLog, classify_side, seconds_until_rollover, ROLLOVER_HOUR_ICT,
)
from app.market_data.trading_calendar import VN_TZ

pytestmark = pytest.mark.asyncio  # async cases; the pure helpers below are sync


def _state_with_book(bid=21_850, ask=21_900):
    s = MarketState()
    s.apply_bidask_event({"Ticker": "HPG", "Best1Bid": bid, "Best1Ask": ask})
    return s


def _trade(state, price, when="2026-09-07T09:20:00+07:00", vol=300):
    return state.apply_trade_event({
        "Ticker": "HPG", "TradingDate": when, "Close": price,
        "Reference": 21_700, "MatchVolume": vol, "TotalMatchVolume": 1_000_000,
    })


# ------------------------------------------------------------------ side rule
async def test_side_is_derived_from_the_book_and_left_blank_inside_the_spread():
    assert classify_side(21_900, 21_850, 21_900) == "B"   # at the ask
    assert classify_side(21_950, 21_850, 21_900) == "B"   # through the ask
    assert classify_side(21_850, 21_850, 21_900) == "S"   # at the bid
    assert classify_side(21_800, 21_850, 21_900) == "S"
    assert classify_side(21_870, 21_850, 21_900) is None  # genuinely ambiguous
    assert classify_side(21_870, None, None) is None      # no book, no guess


# ------------------------------------------------------------------ retention
async def test_retention_targets_0800_ict_the_next_morning():
    during = datetime(2026, 9, 7, 10, 0, tzinfo=VN_TZ)
    secs = seconds_until_rollover(during)
    assert during + timedelta(seconds=secs) == datetime(2026, 9, 8, ROLLOVER_HOUR_ICT, 0, tzinfo=VN_TZ)


async def test_after_the_close_the_tape_still_survives_the_night():
    evening = datetime(2026, 9, 7, 21, 0, tzinfo=VN_TZ)
    assert seconds_until_rollover(evening) == 11 * 3600


async def test_just_before_rollover_the_window_is_still_positive():
    assert seconds_until_rollover(datetime(2026, 9, 7, 7, 59, tzinfo=VN_TZ)) >= 60


# ---------------------------------------------------------------- recording
async def test_a_match_prints_with_price_change_volume_and_side():
    state = _state_with_book()
    log = TradedLog(max_entries=10)
    quote, diff = _trade(state, 21_900)
    entry = log.record(quote, diff)
    assert entry is not None
    assert entry["price"] == 21_900
    assert entry["volume"] == 300
    assert entry["side"] == "B"          # printed at the ask
    assert entry["time"] == "09:20:00"
    assert entry["change"] == 200        # derived vs the 21,700 reference
    # the state rounds its canonical fraction to 6dp
    assert entry["change_percent"] == pytest.approx(200 / 21_700, abs=1e-6)


async def test_a_frame_that_carries_no_new_match_never_prints():
    """The 20s session poll restates session totals; it must not add a tape row."""
    state = _state_with_book()
    log = TradedLog(max_entries=10)
    quote, diff = _trade(state, 21_900)
    log.record(quote, diff)
    book_quote, book_diff = state.apply_bidask_event({
        "Ticker": "HPG", "Best1Bid": 21_860, "Best1Ask": 21_910,
    })
    assert log.record(book_quote, book_diff) is None
    assert log.get("HPG")["count"] == 1


async def test_the_same_match_redelivered_after_a_reconnect_prints_once():
    state = _state_with_book()
    log = TradedLog(max_entries=10)
    quote, diff = _trade(state, 21_900)
    log.record(quote, diff)
    assert log.record(quote, diff) is None
    assert log.get("HPG")["count"] == 1


async def test_the_tape_is_newest_first_and_bounded():
    state = _state_with_book()
    log = TradedLog(max_entries=3)
    for i, price in enumerate([21_800, 21_850, 21_900, 21_950]):
        q, d = _trade(state, price, when=f"2026-09-07T09:2{i}:00+07:00")
        log.record(q, d)
    items = log.get("HPG")["items"]
    assert [i["price"] for i in items] == [21_950, 21_900, 21_850]  # newest first, capped


async def test_a_new_session_starts_a_clean_tape():
    state = _state_with_book()
    log = TradedLog(max_entries=10)
    q, d = _trade(state, 21_900)
    log.record(q, d)
    q2, d2 = _trade(state, 22_000, when="2026-09-08T09:16:00+07:00")
    log.record(q2, d2)
    tape = log.get("HPG")
    assert tape["count"] == 1
    assert tape["session_date"] == "2026-09-08"


async def test_the_response_declares_the_side_is_derived():
    log = TradedLog()
    assert log.get("HPG")["side_basis"] == "DERIVED_FROM_BOOK"


async def test_a_missing_redis_client_is_not_an_error():
    """The tape degrades to memory-only rather than failing the feed."""
    state = _state_with_book()
    log = TradedLog(max_entries=5)
    q, d = _trade(state, 21_900)
    entry = log.record(q, d)
    await log.persist("HPG", entry)    # no client attached
    assert await log.restore(["HPG"]) == 0
    assert log.get("HPG")["count"] == 1


# --------------------------------------------------------------------------- #
# Shared, session-long history. The tape is server-side so every browser and every
# machine reads the SAME prints; a redeploy or a second laptop must not start empty.
# --------------------------------------------------------------------------- #
class _FakeRedis:
    """Minimal list-semantics stand-in: rpush / ltrim / lrange / delete / expire."""

    def __init__(self):
        self.lists: dict[str, list[str]] = {}
        self.ttl: dict[str, int] = {}
        self.writes = 0

    def pipeline(self):
        outer = self

        class _P:
            def __init__(self): self.ops = []
            def rpush(self, k, v): self.ops.append(("rpush", k, v)); return self
            def ltrim(self, k, a, b): self.ops.append(("ltrim", k, a, b)); return self
            def expire(self, k, s): self.ops.append(("expire", k, s)); return self
            async def execute(self):
                for op in self.ops:
                    if op[0] == "rpush":
                        outer.lists.setdefault(op[1], []).append(op[2]); outer.writes += 1
                    elif op[0] == "ltrim":
                        outer.lists[op[1]] = outer.lists.get(op[1], [])[op[2]:] if op[2] < 0 else outer.lists.get(op[1], [])
                    elif op[0] == "expire":
                        outer.ttl[op[1]] = op[3] if len(op) > 3 else op[2]
        return _P()

    async def lrange(self, key, start, end):
        items = self.lists.get(key, [])
        return items[start:] if end == -1 else items[start:end + 1]

    async def delete(self, key):
        self.lists.pop(key, None)


async def test_a_redeploy_mid_session_does_not_wipe_the_tape():
    """A restart used to leave the panel empty until the next print. The stored tape is
    reloaded into the memory window, so the process comes back with history."""
    state = _state_with_book()
    redis = _FakeRedis()
    log = TradedLog(max_entries=6000)
    log.set_redis(redis)

    for i in range(250):
        q, d = _trade(state, 21_800 + i, when=f"2026-09-07T09:{20 + i // 60:02d}:{i % 60:02d}+07:00")
        entry = log.record(q, d)
        if entry:
            await log.persist("HPG", entry)

    # A brand-new process (a different machine's request hits the same server, but this
    # models the redeploy that used to wipe it) rebuilds from Redis.
    fresh = TradedLog(max_entries=6000)
    fresh.set_redis(redis)
    assert await fresh.restore(["HPG"]) == 1
    assert fresh.get("HPG", limit=6000)["count"] == 250      # not the old 200 cap
    assert fresh.get("HPG")["items"][0]["price"] == 22_049   # newest first


async def test_persisting_is_constant_work_per_print():
    """Retention is affordable only because a print appends. The old blob rewrote the whole
    tape each time, which at session length would have been ~1 MB per print."""
    state = _state_with_book()
    redis = _FakeRedis()
    log = TradedLog(max_entries=6000)
    log.set_redis(redis)
    for i in range(100):
        q, d = _trade(state, 21_800 + i, when=f"2026-09-07T09:2{i // 10}:{i % 60:02d}+07:00")
        e = log.record(q, d)
        if e:
            await log.persist("HPG", e)
    # one rpush per print, not one full-tape serialisation
    assert redis.writes == 100
    assert len(redis.lists["cw_research:traded_log:v1:HPG"]) == 100


async def test_a_stored_tape_from_an_earlier_session_is_not_restored_into_today():
    redis = _FakeRedis()
    key = "cw_research:traded_log:v1:HPG"
    redis.lists[key] = [json.dumps({
        "ts": 1, "time": "09:20:00", "price": 21_000, "change": None,
        "change_percent": None, "volume": 100, "side": "B", "session_date": "2999-01-01",
    })]
    log = TradedLog(max_entries=100)
    log.set_redis(redis)
    assert await log.restore(["HPG"]) == 0
    assert log.get("HPG")["count"] == 0


async def test_a_session_rollover_clears_the_stored_tape():
    state = _state_with_book()
    redis = _FakeRedis()
    log = TradedLog(max_entries=100)
    log.set_redis(redis)

    q, d = _trade(state, 21_900)
    await log.persist("HPG", log.record(q, d))
    key = "cw_research:traded_log:v1:HPG"
    assert len(redis.lists[key]) == 1

    q2, d2 = _trade(state, 22_000, when="2026-09-08T09:16:00+07:00")
    entry = log.record(q2, d2)
    await log.persist("HPG", entry)
    # yesterday's print is gone, today's is the only one stored
    assert len(redis.lists[key]) == 1
    assert json.loads(redis.lists[key][0])["session_date"] == "2026-09-08"


async def test_the_endpoint_reads_the_shared_tape_not_this_process_memory():
    """The second-machine fix. Memory holds only a recent window; the shared Redis tape
    holds the session, and that is what a client must be served."""
    state = _state_with_book()
    redis = _FakeRedis()
    log = TradedLog(max_entries=6000, memory_entries=50)
    log.set_redis(redis)

    for i in range(400):
        q, d = _trade(state, 21_800 + i, when=f"2026-09-07T09:{20 + i // 60:02d}:{i % 60:02d}+07:00")
        entry = log.record(q, d)
        if entry:
            await log.persist("HPG", entry)

    assert log.get("HPG", limit=6000)["count"] == 50          # memory is just a window
    shared = await log.get_session("HPG", limit=6000)
    assert shared["count"] == 400                              # the session, in full
    assert shared["items"][0]["price"] == 22_199               # newest first
    assert shared["items"][-1]["price"] == 21_800              # ...back to the open


async def test_a_redis_outage_degrades_to_recent_prints_rather_than_nothing():
    state = _state_with_book()
    log = TradedLog(max_entries=6000, memory_entries=50)

    class _Broken:
        async def lrange(self, *_a):
            raise RuntimeError("connection reset")

    log.set_redis(_Broken())
    for i in range(80):
        q, d = _trade(state, 21_800 + i, when=f"2026-09-07T09:20:{i % 60:02d}+07:00")
        log.record(q, d)
    assert (await log.get_session("HPG", limit=6000))["count"] == 50
