import asyncio
import json
import time

import pytest

from app.market_data.providers.fiinquant_provider import FiinQuantProvider


class _Transport:
    def __init__(self, handler):
        self.on_message = handler
        self.manually_closing = False
        self.reconnection_handler = None
        self._ws = None


class _Hub:
    def __init__(self, transport):
        self.transport = transport


class _Stream:
    def __init__(self, handler=lambda app, raw: None):
        self.hub_connection = _Hub(_Transport(handler))
        self.connected = True
        self.stopped = False

    def stop(self):
        self.stopped = True
        self.connected = False


class _LazyStream:
    def __init__(self, handler):
        self.hub_connection = None
        self._handler = handler

    def _build_connection(self):
        self.hub_connection = _Hub(_Transport(self._handler))
        return self.hub_connection


def _provider() -> FiinQuantProvider:
    provider = FiinQuantProvider(username="u", password="p", max_symbols=33)
    provider._signalrcore_version = lambda: "0.9.71"
    provider._stream_generation = 1
    return provider


def test_provider_adapter_reassembles_partial_json_before_signalrcore_handler():
    decoded = []

    def _parse(_app, raw):
        decoded.extend(json.loads(frame) for frame in raw.split("\x1e") if frame)

    provider = _provider()
    stream = _Stream(_parse)
    assert provider._install_signalr_frame_adapter(stream, 1, "trade") is True

    stream.hub_connection.transport.on_message(None, '{"type":1,"value":')
    assert decoded == []
    assert provider.get_health()["signalr_buffered_bytes"] > 0

    stream.hub_connection.transport.on_message(None, '2}\x1e')
    assert decoded == [{"type": 1, "value": 2}]
    assert provider.get_health()["signalr_decode_error_count"] == 0
    provider._release_signalr_frame_adapter(stream)


def test_provider_wraps_fiinquant_lazy_hub_builder_before_start():
    decoded = []
    stream = _LazyStream(lambda _app, raw: decoded.append(raw))
    provider = _provider()

    assert provider._install_signalr_frame_adapter(stream, 1, "trade") is True
    hub = stream._build_connection()
    hub.transport.on_message(None, "{}\x1e")

    assert decoded == ["{}\x1e"]
    assert hub.transport.reconnection_handler is None
    assert provider.get_health()["signalr_adapter_active_count"] == 1
    provider._release_signalr_frame_adapter(stream)


def test_complete_bad_frame_is_counted_without_payload_and_marks_reconnecting():
    def _reject(_app, _raw):
        raise ValueError("sensitive raw payload")

    provider = _provider()
    provider._is_connected = True
    provider._active_symbols = ["HPG"]
    stream = _Stream(_reject)
    assert provider._install_signalr_frame_adapter(stream, 1, "trade") is True

    stream.hub_connection.transport.on_message(None, '{"secret":true}\x1e')

    health = provider.get_health()
    assert health["signalr_decode_error_count"] == 1
    assert health["last_signalr_frame_error_kind"] == "frame_error"
    assert health["upstream_status"] == "RECONNECTING"
    assert "secret" not in str(health)
    provider._release_signalr_frame_adapter(stream)


def test_live_requires_a_fresh_tick_from_the_current_stream():
    provider = _provider()
    provider._is_connected = True
    provider._upstream_status = "CONNECTED"
    provider._active_symbols = ["HPG"]
    provider._trade_stream = _Stream()
    provider._current_stream_started_at_monotonic = time.monotonic()
    provider._market_is_active = lambda: True

    assert provider.get_health()["upstream_status"] == "CONNECTING"
    assert provider.get_health()["feed_fresh"] is False

    provider._on_trade_raw({"Ticker": "HPG", "Close": 22_100})
    assert provider.get_health()["upstream_status"] == "LIVE"
    assert provider.get_health()["feed_fresh"] is True

    stale_tick = int(
        (time.time() - provider._feed_freshness_seconds - 1) * 1000
    )
    provider._current_trade_tick_at_ms = stale_tick
    provider._current_stream_last_tick_at_ms = stale_tick
    assert provider.get_health()["upstream_status"] == "STALE"
    assert provider.get_health()["feed_fresh"] is False


def test_live_requires_every_expected_channel_to_be_connected_and_fresh():
    provider = _provider()
    provider._is_connected = True
    provider._upstream_status = "CONNECTED"
    provider._active_symbols = ["HPG"]
    provider._trade_stream = _Stream()
    provider._bidask_stream = _Stream()
    provider._current_stream_requires_book = True
    provider._current_stream_started_at_monotonic = time.monotonic()
    provider._market_is_active = lambda: True

    provider._on_trade_raw({"Ticker": "HPG", "Close": 22_100})
    health = provider.get_health()
    assert health["trade_feed_fresh"] is True
    assert health["book_feed_fresh"] is False
    assert health["feed_fresh"] is False
    assert health["upstream_status"] == "CONNECTING"

    provider._on_bidask_raw({"Ticker": "HPG", "BidPrice1": 22_050})
    assert provider.get_health()["upstream_status"] == "LIVE"

    provider._current_book_tick_at_ms = int(
        (time.time() - provider._feed_freshness_seconds - 1) * 1000
    )
    health = provider.get_health()
    assert health["book_feed_fresh"] is False
    assert health["feed_fresh"] is False
    assert health["upstream_status"] == "STALE"

    provider._current_book_tick_at_ms = int(time.time() * 1000)
    provider._bidask_stream.connected = False
    health = provider.get_health()
    assert health["feed_fresh"] is False
    assert health["upstream_status"] == "RECONNECTING"


@pytest.mark.asyncio
async def test_status_callback_fires_once_when_complete_feed_transitions_live():
    provider = _provider()
    provider._loop = asyncio.get_running_loop()
    provider._is_connected = True
    provider._upstream_status = "CONNECTED"
    provider._active_symbols = ["HPG"]
    provider._trade_stream = _Stream()
    provider._bidask_stream = _Stream()
    provider._current_stream_requires_book = True
    provider._current_stream_started_at_monotonic = time.monotonic()
    provider._market_is_active = lambda: True
    notifications = []
    provider.set_status_callback(
        lambda: notifications.append(provider.get_health()["upstream_status"])
    )

    provider._on_trade_raw({"Ticker": "HPG", "Close": 22_100})
    assert notifications == []
    provider._on_bidask_raw({"Ticker": "HPG", "BidPrice1": 22_050})
    assert notifications == ["LIVE"]

    provider._on_trade_raw({"Ticker": "HPG", "Close": 22_150})
    provider._on_bidask_raw({"Ticker": "HPG", "BidPrice1": 22_100})
    assert notifications == ["LIVE"]
