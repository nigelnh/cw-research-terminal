"""Shared helpers for the Step-10 hardening tests."""

from __future__ import annotations

import pytest
from starlette.requests import HTTPConnection

from app.security.policies import policy_table


def make_conn(client_host: str | None = "203.0.113.9", headers: dict | None = None) -> HTTPConnection:
    """Build a synthetic HTTP connection for client-IP unit tests."""
    raw_headers = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/market/quote/HPG",
        "headers": raw_headers,
        "client": (client_host, 44444) if client_host else None,
        "server": ("testserver", 80),
        "scheme": "http",
        "query_string": b"",
    }
    return HTTPConnection(scope)


@pytest.fixture
def clear_policy_cache():
    policy_table.cache_clear()
    yield
    policy_table.cache_clear()
