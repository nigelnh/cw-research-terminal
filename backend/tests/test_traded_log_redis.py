"""The traded-log tape against a real Redis server and the production client settings.

On 2026-09-30 between 10:49 and 10:52 ICT, prints, quote batches and the quant cache all
failed with "Too many connections": every print started its own task and its own pipeline,
and redis-py 8's async pool fails the 101st concurrent connection at once instead of
waiting. The fakes in test_traded_log.py cannot see that - it needs a real pool - so these
tests start a throwaway `redis-server` and skip where none is installed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import socket
import subprocess
import time

import pytest

from app.market_data.redis_market_state_store import RedisMarketStateStore
from app.market_data.traded_log import TradedLog

pytestmark = pytest.mark.asyncio

SESSION = "2026-09-30"


@pytest.fixture
def redis_url():
    binary = shutil.which("redis-server")
    if not binary:
        pytest.skip("redis-server is not installed")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    proc = subprocess.Popen(
        [binary, "--port", str(port), "--bind", "127.0.0.1", "--save", "", "--appendonly", "no"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 5
    while True:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            if proc.poll() is not None or time.monotonic() > deadline:
                proc.kill()
                pytest.skip("redis-server did not start")
            time.sleep(0.02)
    try:
        yield f"redis://127.0.0.1:{port}/0"
    finally:
        proc.terminate()
        proc.wait(timeout=5)


@pytest.fixture
async def store(redis_url):
    """The warm-cache store exactly as production builds it - same client, same pool."""
    store = RedisMarketStateStore(redis_url=redis_url, enabled=True)
    await store.initialize()
    assert store.is_available()
    try:
        yield store
    finally:
        await store.close()


def _prints(symbols: int, each: int) -> list[tuple[str, dict]]:
    return [
        (f"S{s:03d}", {"id": f"S{s:03d}-{i}", "ts": i, "price": 1000 + i, "session_date": SESSION})
        for i in range(each) for s in range(symbols)
    ]


async def _stored(client, symbol: str) -> list[int]:
    raw = await client.lrange(f"cw_research:traded_log:v3:{symbol}:{SESSION}", 0, -1)
    return [json.loads(item)["price"] for item in raw]


async def test_a_burst_of_prints_does_not_drain_the_pool_the_caches_share(store, caplog):
    """600 prints landing together, the way the realtime handler used to fire them, with a
    market-overview save in the same burst. Before: 500 of the 600 prints lost, and the
    save failed too."""
    log = TradedLog(max_entries=8000, memory_entries=600)
    log.set_redis(store._client)
    burst = _prints(symbols=60, each=10)

    with caplog.at_level(logging.WARNING):
        await asyncio.gather(
            *(log.persist(symbol, entry) for symbol, entry in burst),
            store.save_market_overview({"indices": [], "marker": "saved during the burst"}),
        )

    for s in range(60):
        assert await _stored(store._client, f"S{s:03d}") == [1000 + i for i in range(10)]
    assert (await store.load_market_overview())["marker"] == "saved during the burst"
    assert "Too many connections" not in caplog.text
    assert store.is_available()


async def test_queued_prints_reach_redis_in_order_after_a_flush(store):
    """The realtime handler now only queues (no task per print); one writer drains it."""
    log = TradedLog(max_entries=8000, memory_entries=600)
    log.set_redis(store._client)
    for symbol, entry in _prints(symbols=5, each=40):
        log.enqueue(symbol, entry)
    await log.flush()
    for s in range(5):
        assert await _stored(store._client, f"S{s:03d}") == [1000 + i for i in range(40)]
