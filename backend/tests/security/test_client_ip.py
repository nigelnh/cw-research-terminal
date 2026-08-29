"""Trusted-proxy / client-IP extraction (Step 10 section 3)."""

from __future__ import annotations

import pytest

from app.core.config import settings
import app.security.client_ip as client_ip_mod
from app.security.client_ip import (
    _trusted_networks_cached,
    resolve_client_ip,
    resolve_client_key,
)
from tests.security.conftest import make_conn


@pytest.fixture(autouse=True)
def _fresh_cidr_cache():
    _trusted_networks_cached.cache_clear()
    client_ip_mod._railway_unverified_warned = False
    yield
    _trusted_networks_cached.cache_clear()


@pytest.fixture
def railway_mode(monkeypatch):
    """CLIENT_IP_TRUST_MODE=railway, production, on a verified Railway service."""
    monkeypatch.setattr(settings, "CLIENT_IP_TRUST_MODE", "railway")
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setenv("RAILWAY_PROJECT_ID", "proj_test123")
    monkeypatch.delenv("RAILWAY_SERVICE_ID", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT_ID", raising=False)


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


# --------------------------------------------------------------------------- #
# CLIENT_IP_TRUST_MODE resolution
# --------------------------------------------------------------------------- #
def test_mode_defaults_to_direct(monkeypatch):
    monkeypatch.setattr(settings, "CLIENT_IP_TRUST_MODE", "")
    monkeypatch.setattr(settings, "RATE_LIMIT_TRUST_PROXY", False)
    assert settings.client_ip_trust_mode() == "direct"


def test_mode_back_compat_cidr_from_legacy_flag(monkeypatch):
    monkeypatch.setattr(settings, "CLIENT_IP_TRUST_MODE", "")
    monkeypatch.setattr(settings, "RATE_LIMIT_TRUST_PROXY", True)
    assert settings.client_ip_trust_mode() == "cidr"


def test_explicit_mode_overrides_legacy_flag(monkeypatch):
    monkeypatch.setattr(settings, "CLIENT_IP_TRUST_MODE", "direct")
    monkeypatch.setattr(settings, "RATE_LIMIT_TRUST_PROXY", True)
    assert settings.client_ip_trust_mode() == "direct"


# --------------------------------------------------------------------------- #
# 'railway' mode
# --------------------------------------------------------------------------- #
def test_railway_mode_trusts_leftmost_xff(railway_mode):
    # Railway's edge rewrites XFF: leftmost is the real client, rest are infra hops.
    conn = make_conn("100.64.0.3", {"x-forwarded-for": "198.51.100.42, 100.64.0.1"})
    assert resolve_client_ip(conn) == "198.51.100.42"


def test_railway_mode_never_reads_client_x_real_ip(railway_mode):
    # Attacker sets BOTH headers. railway mode must key on leftmost XFF, never X-Real-IP.
    conn = make_conn(
        "100.64.0.3",
        {"x-forwarded-for": "198.51.100.42, 100.64.0.1", "x-real-ip": "9.9.9.9"},
    )
    assert resolve_client_ip(conn) == "198.51.100.42"


def test_railway_mode_no_xff_falls_back_to_socket_peer(railway_mode):
    conn = make_conn("100.64.0.3", {"x-real-ip": "9.9.9.9"})
    assert resolve_client_ip(conn) == "100.64.0.3"  # NOT 9.9.9.9


def test_railway_mode_garbage_leftmost_falls_back(railway_mode):
    conn = make_conn("100.64.0.3", {"x-forwarded-for": "not-an-ip, 100.64.0.1"})
    assert resolve_client_ip(conn) == "100.64.0.3"


def test_railway_mode_degrades_to_direct_when_not_production(monkeypatch):
    monkeypatch.setattr(settings, "CLIENT_IP_TRUST_MODE", "railway")
    monkeypatch.setattr(settings, "ENVIRONMENT", "staging")
    monkeypatch.setenv("RAILWAY_PROJECT_ID", "proj_test123")
    conn = make_conn("100.64.0.3", {"x-forwarded-for": "198.51.100.42"})
    assert resolve_client_ip(conn) == "100.64.0.3"  # header NOT trusted off-production


def test_railway_mode_degrades_to_direct_without_railway_marker(monkeypatch):
    monkeypatch.setattr(settings, "CLIENT_IP_TRUST_MODE", "railway")
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.delenv("RAILWAY_PROJECT_ID", raising=False)
    monkeypatch.delenv("RAILWAY_SERVICE_ID", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT_ID", raising=False)
    conn = make_conn("100.64.0.3", {"x-forwarded-for": "198.51.100.42"})
    assert resolve_client_ip(conn) == "100.64.0.3"  # no RAILWAY_* proof -> don't trust


def test_railway_mode_key_shape(railway_mode):
    conn = make_conn("100.64.0.3", {"x-forwarded-for": "198.51.100.42"})
    assert resolve_client_key(conn) == "ip:198.51.100.42"
    assert resolve_client_key(conn, subject="u-1") == "sub:u-1"
