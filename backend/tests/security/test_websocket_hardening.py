"""WebSocket hardening (Step 10 sections 9, 10, 27).

The backend keeps ONE shared market provider regardless of how many browser clients
connect - these tests only bound per-client / global connection and message abuse.
"""

from __future__ import annotations

import contextlib
import json

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.config import settings
from app.main import app
from app.market_data.market_websocket import manager

client = TestClient(app)


@pytest.fixture(autouse=True)
def _ws_baseline():
    # start from a clean connection ledger
    manager._active_connections.clear()
    manager._conn_by_ip.clear()
    yield
    manager._active_connections.clear()
    manager._conn_by_ip.clear()


def _drain_status(ws):
    msg = json.loads(ws.receive_text())
    assert msg["type"] == "status"
    return msg


def test_normal_subscribe_path_unchanged():
    with client.websocket_connect("/ws/market") as ws:
        _drain_status(ws)
        ws.send_text(json.dumps({"type": "subscribe", "symbols": ["HPG", "CHPG2602"]}))
        ws.send_text(json.dumps({"type": "unsubscribe", "symbols": ["CHPG2602"]}))
    assert manager.active_count == 0  # cleanup released the slot


def test_public_realtime_kill_switch(monkeypatch):
    monkeypatch.setattr(settings, "PUBLIC_REALTIME_ENABLED", False)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/market"):
            pass
    assert client.get("/health").status_code == 200  # rest of app fine


def test_global_connection_ceiling(monkeypatch):
    monkeypatch.setattr(settings, "WS_MAX_CONNECTIONS_TOTAL", 2)
    monkeypatch.setattr(settings, "WS_MAX_CONNECTIONS_PER_IP", 99)
    with client.websocket_connect("/ws/market") as a, client.websocket_connect("/ws/market") as b:
        _drain_status(a)
        _drain_status(b)
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws/market"):
                pass


def test_per_client_connection_cap(monkeypatch):
    monkeypatch.setattr(settings, "WS_MAX_CONNECTIONS_TOTAL", 99)
    monkeypatch.setattr(settings, "WS_MAX_CONNECTIONS_PER_IP", 2)
    with client.websocket_connect("/ws/market") as a, client.websocket_connect("/ws/market") as b:
        _drain_status(a)
        _drain_status(b)
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws/market"):
                pass


def test_too_many_symbols_is_rejected_without_closing(monkeypatch):
    monkeypatch.setattr(settings, "WS_MAX_SYMBOLS_PER_CLIENT", 5)
    with client.websocket_connect("/ws/market") as ws:
        _drain_status(ws)
        ws.send_text(json.dumps({"type": "subscribe", "symbols": [f"S{i}" for i in range(50)]}))
        reply = json.loads(ws.receive_text())
        assert reply["type"] == "error" and reply["error"] == "too_many_symbols"
        # connection still usable
        ws.send_text(json.dumps({"type": "subscribe", "symbols": ["HPG"]}))


def test_oversized_message_closes_connection(monkeypatch):
    monkeypatch.setattr(settings, "WS_MAX_MESSAGE_BYTES", 256)
    with client.websocket_connect("/ws/market") as ws:
        _drain_status(ws)
        ws.send_text(json.dumps({"type": "subscribe", "symbols": ["X" * 4000]}))
        with pytest.raises(WebSocketDisconnect):
            ws.receive_text()


def test_single_malformed_message_is_tolerated():
    with client.websocket_connect("/ws/market") as ws:
        _drain_status(ws)
        ws.send_text("this is not json")
        # still usable
        ws.send_text(json.dumps({"type": "subscribe", "symbols": ["HPG"]}))


def test_repeated_malformed_messages_close_connection():
    with client.websocket_connect("/ws/market") as ws:
        _drain_status(ws)
        for _ in range(12):  # threshold is 10
            with contextlib.suppress(Exception):
                ws.send_text("still not json")
        with pytest.raises(WebSocketDisconnect):
            ws.receive_text()


def test_message_rate_limit_closes_flooding_connection(monkeypatch):
    monkeypatch.setattr(settings, "WS_MESSAGE_BURST", 5)
    monkeypatch.setattr(settings, "WS_MESSAGE_WINDOW_SECONDS", 60.0)
    with client.websocket_connect("/ws/market") as ws:
        _drain_status(ws)
        for _ in range(20):
            with contextlib.suppress(Exception):
                ws.send_text(json.dumps({"type": "noop"}))
        with pytest.raises(WebSocketDisconnect):
            ws.receive_text()


def test_connection_cleanup_releases_counters(monkeypatch):
    monkeypatch.setattr(settings, "WS_MAX_CONNECTIONS_PER_IP", 3)
    for _ in range(5):
        with client.websocket_connect("/ws/market") as ws:
            _drain_status(ws)
    assert manager.active_count == 0
    assert sum(manager._conn_by_ip.values()) == 0


def test_one_shared_provider_regardless_of_clients():
    from app.market_data.market_subscription_manager import subscription_manager

    p0 = subscription_manager.provider
    with client.websocket_connect("/ws/market") as a, client.websocket_connect("/ws/market") as b:
        _drain_status(a)
        _drain_status(b)
        assert subscription_manager.provider is p0  # no per-client upstream
