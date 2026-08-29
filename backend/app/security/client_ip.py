"""Trusted-proxy-aware client identity for rate limiting.

Security rule: ``X-Forwarded-For`` / ``X-Real-IP`` are attacker-controlled unless the
request's *direct* peer is a configured trusted proxy. We only walk the XFF chain when
``RATE_LIMIT_TRUST_PROXY`` is on AND ``request.client.host`` is inside
``TRUSTED_PROXY_CIDRS``; then we take the right-most address that is not itself a trusted
proxy (the address the edge proxy observed). Otherwise the key is the direct socket peer.

An attacker connecting directly and sending ``X-Forwarded-For: 1.2.3.4`` therefore keys on
their real socket address and cannot escape or pivot the limiter.
"""

from __future__ import annotations

import ipaddress
from functools import lru_cache

from starlette.requests import HTTPConnection

from app.core.config import settings

_UNKNOWN = "unknown"


@lru_cache(maxsize=1)
def _trusted_networks_cached(raw: str) -> tuple[ipaddress._BaseNetwork, ...]:
    nets: list[ipaddress._BaseNetwork] = []
    for cidr in (c.strip() for c in raw.split(",") if c.strip()):
        try:
            nets.append(ipaddress.ip_network(cidr, strict=False))
        except ValueError:
            continue
    return tuple(nets)


def _trusted_networks() -> tuple[ipaddress._BaseNetwork, ...]:
    return _trusted_networks_cached(settings.TRUSTED_PROXY_CIDRS or "")


def _ip_in_trusted(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    return any(ip in net for net in _trusted_networks())


def resolve_client_ip(conn: HTTPConnection) -> str:
    """The best available client IP string. Works for both HTTP requests and WS connections."""
    direct = conn.client.host if conn.client else _UNKNOWN

    if not settings.RATE_LIMIT_TRUST_PROXY:
        return direct
    if direct == _UNKNOWN or not _ip_in_trusted(direct):
        # direct peer is not a trusted proxy -> ignore any forwarding headers
        return direct

    xff = conn.headers.get("x-forwarded-for", "")
    chain = [p.strip() for p in xff.split(",") if p.strip()]
    for addr in reversed(chain):
        if not _ip_in_trusted(addr):
            return addr

    real_ip = conn.headers.get("x-real-ip", "").strip()
    if real_ip and not _ip_in_trusted(real_ip):
        return real_ip
    return direct


def resolve_client_key(conn: HTTPConnection, *, subject: str | None = None) -> str:
    """Rate-limit key. Prefers a verified auth subject when available (stable, per-user),
    otherwise the trusted-proxy-aware client IP. Callers pass ``subject`` ONLY after the
    token has been verified - never a client-declared identity."""
    if subject:
        return f"sub:{subject}"
    return f"ip:{resolve_client_ip(conn)}"
