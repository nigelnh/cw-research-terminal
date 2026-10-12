"""Status frames go out when something a client acts on changes, plus a heartbeat.

The provider reports its health after every SSI realtime frame - 40 to 70 a second in a
busy session (2026-10-12) - and each report reached every browser as a full status frame
carrying the 370-symbol universe list. Each one re-rendered the browser's session
consumers: half of the main thread, in stalls that swallowed the 300 ms value flashes.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.market_data import market_websocket
from app.market_data.market_state import MarketState
from app.market_data.market_state_store import NullMarketStateStore
from app.market_data.market_subscription_manager import SubscriptionManager, subscription_manager
from app.market_data.market_websocket import STATUS_HEARTBEAT_SECONDS, MarketConnectionManager
from app.market_data.providers.vnstock_provider import VnstockProvider
from app.market_data.trading_calendar import VN_TZ

# A captured SSI price-table frame (MBB), as in test_vnstock_provider.
SSI_FRAME = (
    "MAIN|S#MBB|26550|32400|26500|582000|26450|1505900|||||||||||||||"
    "26600|102800|26650|254300|26700|450500|||||||||||||||26550|1000|26800|hose|"
    "26500|26618|3828200|101926470000|1051200|27997390000|100|0.38|11773300|"
    "313381740000||||28300|24600|26450||||0|s|N||||0|0|VSDMBBX||26800|||||||||||||||||||||27"
)
OBSERVED = datetime(2026, 9, 9, 10, 0, tzinfo=VN_TZ)
UNIVERSE = {"MBB", "CMBB2601"}


def frame(i: int) -> str:
    """The book moves on every frame and a match prints on every tenth - a busy symbol."""
    parts = SSI_FRAME.split("|")
    parts[3] = str(32_400 + i)
    parts[54] = str(11_773_300 + (i // 10) * 100)
    return "|".join(parts)


class Clock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


def browser() -> MagicMock:
    ws = MagicMock()
    ws.scope = {}
    ws.send_text = AsyncMock()
    return ws


def statuses(ws: MagicMock) -> list[dict]:
    sent = [json.loads(call.args[0]) for call in ws.send_text.await_args_list]
    return [message for message in sent if message["type"] == "status"]


async def connect(manager: MarketConnectionManager, ws: MagicMock, symbols=()) -> None:
    """What `connect()` does once the handshake is accepted."""
    manager._active_connections.add(ws)
    manager._client_subscriptions[ws] = set(symbols)
    await ws.send_text(json.dumps(manager._status_message(ws)))


async def drain() -> None:
    for _ in range(3):
        await asyncio.sleep(0)


@pytest.fixture
def wired(monkeypatch):
    """The provider, its subscription manager and a connection manager joined the way the
    app joins them: the provider's status callback is the path under test."""
    provider = VnstockProvider()
    provider._request_floor = 0
    provider._active_symbols = ["MBB"]
    manager_sm = SubscriptionManager(
        provider=provider, state=MarketState(), store=NullMarketStateStore(), max_symbols=400,
    )
    # Quotes are not under test; keep the process-wide tape out of it.
    provider.set_event_callback(lambda *_: None)
    manager_sm._server_universe_symbols = set(UNIVERSE)
    manager_sm._active_symbols = set(UNIVERSE)
    monkeypatch.setattr(market_websocket, "subscription_manager", manager_sm)
    clock = Clock()
    return provider, manager_sm, MarketConnectionManager(clock=clock), clock


@pytest.mark.asyncio
async def test_a_busy_realtime_stream_sends_status_on_change_or_heartbeat_only(wired):
    provider, _, manager, clock = wired
    ws = browser()
    await connect(manager, ws, {"MBB"})

    start = clock.now
    for i in range(600):  # ten seconds at 60 frames a second
        clock.now = start + i / 60
        assert provider._handle_realtime_text(
            frame(i), received_at=OBSERVED + timedelta(seconds=i / 60)
        ) is True
    await drain()

    broadcasts = statuses(ws)[1:]
    # 600 frames used to be 600 status frames. Now: the steady state once, then the
    # heartbeat - and nothing in between, because nothing a client acts on changed.
    assert 1 <= len(broadcasts) <= 10 / STATUS_HEARTBEAT_SECONDS + 1
    # The clocks and tick stamps still move: they ride along with the heartbeat.
    assert broadcasts[-1]["last_book_tick_at"] > broadcasts[0]["last_book_tick_at"]
    # The universe list went out with the connect frame and not again.
    assert all("realtime_universe_symbols" not in message for message in broadcasts)


@pytest.mark.asyncio
async def test_a_feed_change_goes_out_at_once_inside_the_heartbeat(wired):
    provider, _, manager, clock = wired
    ws = browser()
    await connect(manager, ws, {"MBB"})
    provider._notify_status()
    await drain()
    before = len(statuses(ws))

    clock.now += 0.5
    provider._notify_status()
    await drain()
    assert len(statuses(ws)) == before

    clock.now += 0.5
    provider._access.record("market_data", "upstream_unavailable")
    provider._notify_status()
    await drain()
    sent = statuses(ws)
    assert len(sent) == before + 1
    assert sent[-1]["feedStatus"]["code"] == "UPSTREAM_UNAVAILABLE"


@pytest.mark.asyncio
async def test_the_universe_list_goes_once_per_client_and_again_when_it_changes(wired):
    provider, manager_sm, manager, clock = wired
    first, second = browser(), browser()
    await connect(manager, first, {"MBB"})
    provider._notify_status()
    await drain()
    await connect(manager, second)
    clock.now += 0.5
    provider._notify_status()
    await drain()
    for ws in (first, second):
        assert sum("realtime_universe_symbols" in m for m in statuses(ws)) == 1

    # Same size, every symbol live: nothing else in the frame changes, only the list.
    swapped = {"MBB", "CMBB2602"}
    manager_sm._server_universe_symbols = set(swapped)
    manager_sm._active_symbols = set(swapped)
    clock.now += 0.5
    provider._notify_status()
    await drain()
    for ws in (first, second):
        assert statuses(ws)[-1]["realtime_universe_symbols"] == sorted(swapped)


def test_a_ping_reply_does_not_resend_the_universe_list():
    client = TestClient(app)
    with patch.object(subscription_manager, "_server_universe_symbols", {"HPG", "FPT"}):
        with client.websocket_connect("/ws/market") as ws:
            first = json.loads(ws.receive_text())
            ws.send_text(json.dumps({"type": "ping"}))
            reply = json.loads(ws.receive_text())

    assert set(first["realtime_universe_symbols"]) == {"HPG", "FPT"}
    assert reply["type"] == "status"
    assert "realtime_universe_symbols" not in reply
