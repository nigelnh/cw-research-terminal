"""Trusted-proxy / client-IP extraction (Step 10 section 3)."""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.security.client_ip import (
    _trusted_networks_cached,
    resolve_client_ip,
    resolve_client_key,
)
from tests.security.conftest import make_conn


@pytest.fixture(autouse=True)
def _fresh_cidr_cache():
    _trusted_networks_cached.cache_clear()
    yield
    _trusted_networks_cached.cache_clear()


def test_direct_peer_used_when_proxy_trust_disabled(monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_TRUST_PROXY", False)
    conn = make_conn("198.51.100.7", {"x-forwarded-for": "1.2.3.4", "x-real-ip": "9.9.9.9"})
    assert resolve_client_ip(conn) == "198.51.100.7"


def test_spoofed_xff_from_untrusted_direct_peer_is_ignored(monkeypatch):
    # attacker connects directly (not via a trusted proxy) and forges XFF
    monkeypatch.setattr(settings, "RATE_LIMIT_TRUST_PROXY", True)
    monkeypatch.setattr(settings, "TRUSTED_PROXY_CIDRS", "10.0.0.0/8")
    conn = make_conn("203.0.113.50", {"x-forwarded-for": "1.2.3.4"})
    assert resolve_client_ip(conn) == "203.0.113.50"  # NOT 1.2.3.4


def test_xff_honored_only_via_trusted_proxy(monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_TRUST_PROXY", True)
    monkeypatch.setattr(settings, "TRUSTED_PROXY_CIDRS", "10.0.0.0/8,127.0.0.1/32")
    conn = make_conn("10.0.0.5", {"x-forwarded-for": "198.51.100.23"})
    assert resolve_client_ip(conn) == "198.51.100.23"


def test_xff_chain_takes_rightmost_untrusted(monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_TRUST_PROXY", True)
    monkeypatch.setattr(settings, "TRUSTED_PROXY_CIDRS", "10.0.0.0/8")
    # client -> edge(198.51.100.9) -> internal proxy(10.0.0.2) -> us(10.0.0.1)
    conn = make_conn("10.0.0.1", {"x-forwarded-for": "198.51.100.9, 10.0.0.2"})
    assert resolve_client_ip(conn) == "198.51.100.9"


def test_all_addresses_trusted_falls_back_to_direct(monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_TRUST_PROXY", True)
    monkeypatch.setattr(settings, "TRUSTED_PROXY_CIDRS", "10.0.0.0/8")
    conn = make_conn("10.0.0.1", {"x-forwarded-for": "10.0.0.9, 10.0.0.2"})
    assert resolve_client_ip(conn) == "10.0.0.1"


def test_key_uses_verified_subject_when_present(monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_TRUST_PROXY", False)
    conn = make_conn("198.51.100.7")
    assert resolve_client_key(conn) == "ip:198.51.100.7"
    assert resolve_client_key(conn, subject="user-abc") == "sub:user-abc"


def test_garbage_direct_host_does_not_crash(monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_TRUST_PROXY", True)
    monkeypatch.setattr(settings, "TRUSTED_PROXY_CIDRS", "10.0.0.0/8")
    conn = make_conn("testclient", {"x-forwarded-for": "1.2.3.4"})
    assert resolve_client_ip(conn) == "testclient"  # not an IP -> not trusted -> XFF ignored
