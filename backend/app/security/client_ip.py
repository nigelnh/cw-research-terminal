"""Client identity for rate limiting.

The client IP is used ONLY as a rate-limit key (``ip:<addr>``) - never for auth or
access control. ``X-Forwarded-For`` / ``X-Real-IP`` are attacker-controlled unless a
trusted hop sits in front of us, so the resolver has three explicit modes
(``CLIENT_IP_TRUST_MODE``):

* ``direct``  - the socket peer; forwarded headers ignored. Local/dev, or any deploy
  where this app is the edge.
* ``cidr``    - walk ``X-Forwarded-For`` only when the direct peer is inside
  ``TRUSTED_PROXY_CIDRS``; take the right-most address that is not itself a trusted
  proxy (the address that proxy observed).
* ``railway`` - trust ONLY the left-most ``X-Forwarded-For`` entry, and ONLY when
  ``ENVIRONMENT=production`` AND the process is on a verified Railway service. Railway's
  edge strips/rewrites XFF so the left-most entry is the real client; its ``X-Real-IP``
  is unreliable behind the CDN and is never read. If the environment can't be verified
  the mode degrades to ``direct`` (never trusts a header on a box we can't vouch for).

An attacker connecting directly and sending ``X-Forwarded-For: 1.2.3.4`` therefore keys
on their real socket address in every mode and cannot pivot the limiter.
"""

from __future__ import annotations

import ipaddress
import logging
import os
from functools import lru_cache

from starlette.requests import HTTPConnection

from app.core.config import settings

logger = logging.getLogger("cw-research-backend.security")

_UNKNOWN = "unknown"
_railway_unverified_warned = False


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


def _is_ip(addr: str) -> bool:
    try:
        ipaddress.ip_address(addr)
        return True
    except ValueError:
        return False


def _running_on_railway() -> bool:
    """Railway injects these into every service container at runtime; an external client
    cannot set them. Any one is sufficient proof we're on a Railway service."""
    return any(
        os.environ.get(k)
        for k in ("RAILWAY_PROJECT_ID", "RAILWAY_SERVICE_ID", "RAILWAY_ENVIRONMENT_ID")
    )


def _resolve_cidr(conn: HTTPConnection, direct: str) -> str:
    if direct == _UNKNOWN or not _ip_in_trusted(direct):
        return direct  # direct peer is not a trusted proxy -> ignore forwarding headers
    xff = conn.headers.get("x-forwarded-for", "")
    chain = [p.strip() for p in xff.split(",") if p.strip()]
    for addr in reversed(chain):
        if not _ip_in_trusted(addr):
            return addr
    real_ip = conn.headers.get("x-real-ip", "").strip()
    if real_ip and not _ip_in_trusted(real_ip):
        return real_ip
    return direct


def _resolve_railway(conn: HTTPConnection, direct: str) -> str:
    global _railway_unverified_warned
    if not (settings.is_production() and _running_on_railway()):
        if not _railway_unverified_warned:
            logger.warning(
                "CLIENT_IP_TRUST_MODE=railway but %s - not trusting any forwarded header; "
                "keying rate limits on the socket peer.",
                "ENVIRONMENT is not 'production'"
                if not settings.is_production()
                else "no RAILWAY_* env marker is present",
            )
            _railway_unverified_warned = True
        return direct
    # Railway's edge strips inbound XFF and rewrites it; the left-most entry is the real
    # client. We never read X-Real-IP (unreliable behind Railway's CDN).
    xff = conn.headers.get("x-forwarded-for", "")
    first = xff.split(",", 1)[0].strip() if xff else ""
    if first and _is_ip(first):
        return first
    return direct


def resolve_client_ip(conn: HTTPConnection) -> str:
    """The best available client IP string. Works for HTTP requests and WS connections."""
    direct = conn.client.host if conn.client else _UNKNOWN
    mode = settings.client_ip_trust_mode()
    if mode == "railway":
        return _resolve_railway(conn, direct)
    if mode == "cidr":
        return _resolve_cidr(conn, direct)
    return direct  # 'direct'


def resolve_client_key(conn: HTTPConnection, *, subject: str | None = None) -> str:
    """Rate-limit key. Prefers a verified auth subject when available (stable, per-user),
    otherwise the mode-aware client IP. Callers pass ``subject`` ONLY after the token has
    been verified - never a client-declared identity."""
    if subject:
        return f"sub:{subject}"
    return f"ip:{resolve_client_ip(conn)}"
