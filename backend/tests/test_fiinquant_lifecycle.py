"""SignalR / FiinQuant connection-lifecycle tests.

These exercise the provider adapter boundary (``FiinQuantProvider``) against a *fake*
FiinQuantX SDK that faithfully reproduces the two real-world failure modes:

  1. ``<stream>.stop()`` is gated by ``self.connected`` - so once the server closes the
     socket, ``stop()`` no-ops and the SignalR ``ConnectionStateChecker`` keeps its daemon
     thread alive, endlessly "sending" ``PingMessage`` on a dead socket.
  2. Every stream construction hijacks the root logger to DEBUG and attaches an
     un-drained ``CustomHandler`` to it.

No real FiinQuant network calls are made: the only seam is
``FiinQuantProvider._create_session`` and ``FiinQuantX`` is never imported.

Invariant under test:
    **At any moment there is at most one active SignalR connection lifecycle owned by one
    FiinQuantProvider instance** - i.e. the number of running ping loops never exceeds the
    number of streams the provider currently, deliberately owns.
"""

import asyncio
import logging
import sys
import threading
import time

import pytest

from app.market_data.providers.fiinquant_provider import (
    FiinQuantProvider,
    count_signalr_ping_threads,
    reap_orphan_signalr_ping_threads,
)

pytestmark = pytest.mark.asyncio


# --------------------------------------------------------------------------- #
# Fake FiinQuantX SDK
# --------------------------------------------------------------------------- #
_PING_THREAD_NAME = "FakeSignalRPing"


class CustomHandler(logging.Handler):
    """Deliberately named ``CustomHandler`` so ``_tame_sdk_side_effects`` recognises it,
    exactly like ``FiinQuantX``'s real leaking root-logger handler."""

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover - no-op sink
        pass


class _FakeConnectionStateChecker:
    """Shape-compatible with signalrcore's ``ConnectionStateChecker`` (the ping loop)."""

    def __init__(self, ping_function, keep_alive_interval: float = 1.0):
        self.ping_function = ping_function
        self.keep_alive_interval = keep_alive_interval
        self.running = False
        self._thread = None

    def start(self) -> None:
        self.running = True
        self._thread = threading.Thread(target=self.run, name=_PING_THREAD_NAME, daemon=True)
        self._thread.start()

    def run(self) -> None:
        while self.running:
            time.sleep(0.01)
            try:
                self.ping_function()
            except Exception:
                pass

    def stop(self) -> None:
        self.running = False


class _FakeWs:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _FakeTransport:
    def __init__(self, ping_fn) -> None:
        self._ws = _FakeWs()
        self.connection_checker = _FakeConnectionStateChecker(ping_fn)
        self.manually_closing = False
        self.reconnection_handler = object()  # non-None: SDK auto-reconnect "enabled"

    def start(self) -> None:
        self.connection_checker.start()


class _FakeHub:
    def __init__(self, ping_fn) -> None:
        self.transport = _FakeTransport(ping_fn)


class _FakeStream:
    instances: list = []
    start_should_raise = False

    def __init__(self, tickers, callback, kind: str) -> None:
        self.tickers = list(tickers)
        self.callback = callback
        self.kind = kind
        self.connected = False
        self._stop_event = threading.Event()
        self.hub_connection = None
        self.custom_handler = None
        self.ping_count = 0
        _FakeStream.instances.append(self)

    # -- the SDK's PingMessage sender, invoked from the checker thread --
    def _send_ping(self) -> None:
        self.ping_count += 1
        logging.getLogger("SignalRCoreClient").debug("Sending message <PingMessage>")

    def start(self) -> None:
        if _FakeStream.start_should_raise:
            raise RuntimeError("simulated SDK stream start failure")
        # SDK global logging hijack on construction/start:
        root = logging.getLogger()
        root.setLevel(logging.DEBUG)
        logging.getLogger("SignalRCoreClient").setLevel(logging.DEBUG)
        self.custom_handler = CustomHandler()
        root.addHandler(self.custom_handler)

        self.hub_connection = _FakeHub(self._send_ping)
        self.hub_connection.transport.start()
        self.connected = True

    def stop(self) -> None:
        # Reproduce the SDK bug: teardown only happens while self.connected is True.
        if not self.connected:
            return
        self.connected = False
        assert self.hub_connection is not None
        self.hub_connection.transport.connection_checker.stop()
        self.hub_connection.transport._ws.close()
        if self.custom_handler is not None:
            logging.getLogger().removeHandler(self.custom_handler)

    def simulate_server_close(self) -> None:
        """Server dropped the socket. The SDK's internal ``_handle_disconnect`` spins up a
        brand-new ``hub_connection`` (new ping loop) and swaps it in, but never stops the
        old ping loop - so the old ``ConnectionStateChecker`` thread is now referenced
        only by itself: a true orphan that keeps "sending PingMessage" forever."""
        assert self.hub_connection is not None
        self.hub_connection.transport._ws.closed = True
        self.hub_connection = _FakeHub(self._send_ping)  # SDK builds a replacement
        self.hub_connection.transport.start()
        self.connected = True  # SDK believes it has reconnected


class _FakeSession:
    created = 0

    def __init__(self) -> None:
        _FakeSession.created += 1
        self.is_login = True
        self.access_token = "fake-token"

    def Trading_Data_Stream(self, tickers, callback):
        return _FakeStream(tickers, callback, "trade")

    def BidAsk(self, tickers, callback):
        return _FakeStream(tickers, callback, "bidask")

    def Fetch_Trading_Data(self, **kwargs):  # pragma: no cover - not used here
        raise AssertionError("historical fetch not exercised by lifecycle tests")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _alive_ping_threads() -> int:
    return sum(
        1
        for t in threading.enumerate()
        if t.name == _PING_THREAD_NAME and t.is_alive()
    )


async def _wait_until(pred, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        await asyncio.sleep(0.02)
    return pred()


def _make_provider(monkeypatch, *, session_factory=None):
    p = FiinQuantProvider(username="u", password="p", max_symbols=33)
    counter = {"n": 0}

    def _factory():
        counter["n"] += 1
        if session_factory is not None:
            return session_factory()
        return _FakeSession()

    monkeypatch.setattr(p, "_create_session", _factory)
    return p, counter


@pytest.fixture(autouse=True)
def _reset_fakes():
    _FakeStream.instances.clear()
    _FakeStream.start_should_raise = False
    _FakeSession.created = 0
    root = logging.getLogger()
    _baseline = list(root.handlers)
    yield
    # scrub any fake handlers/threads a failing test may have left behind
    for h in list(root.handlers):
        if h not in _baseline:
            root.removeHandler(h)
    reap_orphan_signalr_ping_threads()


# --------------------------------------------------------------------------- #
# T1 - connect -> disconnect: nothing survives
# --------------------------------------------------------------------------- #
async def test_T1_connect_then_disconnect_leaves_no_heartbeat_or_reconnect(monkeypatch):
    p, _ = _make_provider(monkeypatch)
    assert await p.connect() is True
    assert await p.set_subscriptions(["HPG", "CHPG2601"]) is True
    assert count_signalr_ping_threads() >= 1  # a live lifecycle exists

    await p.disconnect()

    assert await _wait_until(lambda: _alive_ping_threads() == 0)
    assert count_signalr_ping_threads() == 0
    assert p._owned_streams == []
    h = p.get_health()
    assert h["active_stream_count"] == 0
    assert h["is_shutting_down"] is True


# --------------------------------------------------------------------------- #
# T2 - repeated connect is idempotent
# --------------------------------------------------------------------------- #
async def test_T2_repeated_connect_is_idempotent(monkeypatch):
    p, calls = _make_provider(monkeypatch)
    results = await asyncio.gather(*(p.connect() for _ in range(8)))
    assert all(results)
    assert calls["n"] == 1
    assert _FakeSession.created == 1
    assert p._connect_count == 1
    assert p._generation == 1
    await p.disconnect()


# --------------------------------------------------------------------------- #
# T3 - server socket close -> exactly one new lifecycle after restart
# --------------------------------------------------------------------------- #
async def test_T3_socket_close_then_restart_yields_exactly_one_lifecycle(monkeypatch):
    p, _ = _make_provider(monkeypatch)
    await p.connect()
    await p.set_subscriptions(["HPG"])
    first = p._trade_stream
    assert first is not None

    first.simulate_server_close()  # SDK-internal reconnect orphans the old ping loop
    assert _alive_ping_threads() >= 3  # old-trade(orphan) + new-trade + bidask

    # a watchlist change triggers a restart; the provider must retire everything first
    assert await p.set_subscriptions(["HPG", "SSI"]) is True

    assert await _wait_until(
        lambda: count_signalr_ping_threads() == len(p._owned_streams)
    )
    assert p._orphans_reaped >= 1  # the reaper caught the SDK's dangling checker
    assert p._generation == 1  # auth session unchanged; only streams restarted
    assert p._stream_restart_count == 2
    assert count_signalr_ping_threads() == 2  # exactly trade + bidask, nothing stale
    assert all(
        s.hub_connection.transport.connection_checker.running for s in p._owned_streams
    )
    await p.disconnect()
    assert await _wait_until(lambda: _alive_ping_threads() == 0)


# --------------------------------------------------------------------------- #
# T4 - many concurrent restarts -> no duplicate clients
# --------------------------------------------------------------------------- #
async def test_T4_concurrent_restarts_never_produce_duplicate_lifecycles(monkeypatch):
    p, _ = _make_provider(monkeypatch)
    await p.connect()

    async def churn(i: int):
        return await p.set_subscriptions([f"SYM{i % 3}", "HPG"])

    await asyncio.gather(*(churn(i) for i in range(12)))

    # lock serialises every transition; at rest, ping loops == currently-owned streams
    assert await _wait_until(
        lambda: count_signalr_ping_threads() == len(p._owned_streams)
    )
    assert count_signalr_ping_threads() <= 2  # trade + bidask, never more
    await p.disconnect()
    assert await _wait_until(lambda: _alive_ping_threads() == 0)


# --------------------------------------------------------------------------- #
# T5 - shutdown while fully live is clean
# --------------------------------------------------------------------------- #
async def test_T5_shutdown_with_active_connection_is_clean(monkeypatch):
    p, _ = _make_provider(monkeypatch)
    await p.connect()
    await p.set_subscriptions(["HPG", "SSI", "VNINDEX"])
    assert count_signalr_ping_threads() >= 1

    await p.disconnect()

    assert await _wait_until(lambda: _alive_ping_threads() == 0)
    root = logging.getLogger()
    assert not any(h.__class__.__name__ == "CustomHandler" for h in root.handlers)
    # a second disconnect is a harmless no-op
    await p.disconnect()
    assert p._disconnect_count == 2


# --------------------------------------------------------------------------- #
# T6 - uvicorn-style restart: old instance retired before new one is active
# --------------------------------------------------------------------------- #
async def test_T6_uvicorn_reload_style_restart_one_active_client(monkeypatch):
    p1, _ = _make_provider(monkeypatch)
    await p1.connect()
    await p1.set_subscriptions(["HPG"])
    await p1.disconnect()
    assert await _wait_until(lambda: _alive_ping_threads() == 0)

    # fresh process => fresh provider instance
    p2, _ = _make_provider(monkeypatch)
    await p2.connect()
    await p2.set_subscriptions(["HPG"])

    assert await _wait_until(lambda: count_signalr_ping_threads() == len(p2._owned_streams))
    assert count_signalr_ping_threads() <= 2
    await p2.disconnect()


# --------------------------------------------------------------------------- #
# T7 - failed reconnect: no tight loop, no orphans, recoverable
# --------------------------------------------------------------------------- #
async def test_T7_failed_reconnect_has_no_tight_loop(monkeypatch):
    # (a) session auth fails
    p, _ = _make_provider(monkeypatch, session_factory=lambda: None)
    assert await p.connect() is False
    assert await p.set_subscriptions(["HPG"]) is False
    assert count_signalr_ping_threads() == 0
    assert p.get_health()["upstream_status"] in ("ERROR", "UNAVAILABLE")

    # (b) session ok but stream.start() raises
    p2, _ = _make_provider(monkeypatch)
    await p2.connect()
    _FakeStream.start_should_raise = True
    assert await p2.set_subscriptions(["HPG"]) is False
    assert await _wait_until(lambda: _alive_ping_threads() == 0)
    assert p2._owned_streams == []
    assert p2.get_health()["last_error"] is not None

    # (c) recovers cleanly once the SDK is healthy again
    _FakeStream.start_should_raise = False
    assert await p2.set_subscriptions(["HPG"]) is True
    assert count_signalr_ping_threads() >= 1
    await p2.disconnect()


# --------------------------------------------------------------------------- #
# T8 - successful reconnect retires the previous lifecycle
# --------------------------------------------------------------------------- #
async def test_T8_successful_reconnect_retires_old_lifecycle(monkeypatch):
    p, _ = _make_provider(monkeypatch)
    await p.connect()
    await p.set_subscriptions(["HPG"])
    old_trade = p._trade_stream
    old_checker = old_trade.hub_connection.transport.connection_checker
    assert old_checker.running is True

    await p.set_subscriptions(["SSI"])
    new_trade = p._trade_stream
    assert new_trade is not old_trade

    assert old_checker.running is False
    assert old_trade.hub_connection.transport._ws.closed is True
    assert new_trade.hub_connection.transport.connection_checker.running is True
    assert count_signalr_ping_threads() == len(p._owned_streams)
    await p.disconnect()


# --------------------------------------------------------------------------- #
# T9 - no real FiinQuant network / SDK import
# --------------------------------------------------------------------------- #
async def test_T9_no_real_fiinquant_import_or_network(monkeypatch):
    assert "FiinQuantX" not in sys.modules
    p, calls = _make_provider(monkeypatch)
    await p.connect()
    await p.set_subscriptions(["HPG", "SSI"])
    await p.disconnect()
    assert "FiinQuantX" not in sys.modules
    assert calls["n"] == 1  # our seam is the only session factory used


# --------------------------------------------------------------------------- #
# Extra - the standalone reaper only touches orphans, never live loops
# --------------------------------------------------------------------------- #
async def test_reaper_spares_excluded_live_checkers(monkeypatch):
    p, _ = _make_provider(monkeypatch)
    await p.connect()
    await p.set_subscriptions(["HPG"])
    live_ids = {
        id(s.hub_connection.transport.connection_checker) for s in p._owned_streams
    }
    reaped = reap_orphan_signalr_ping_threads(exclude=live_ids)
    assert reaped == 0
    assert all(
        s.hub_connection.transport.connection_checker.running for s in p._owned_streams
    )
    await p.disconnect()
