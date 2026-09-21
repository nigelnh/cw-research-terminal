"""Bearer-token guard for machine-to-machine ingestion routes.

This is not user authentication. The only caller is a scheduled GitHub Actions job, which
exists because production cannot fetch fundamentals itself: Railway's egress (AS400940) is
answered with HTTP 403 on Vietcap's VCI GraphQL query while a GitHub-hosted runner
(AS8075) is not. The runner cannot reach the database either - Railway Postgres has no
public TCP proxy and resolves only on `*.railway.internal` - so it hands the rows to the
backend, which writes them over the private network.

Fails CLOSED. An unset token disables the route rather than leaving an unauthenticated
write open on a deployment where someone forgot to configure it.
"""
from __future__ import annotations

import hmac
import logging

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings

logger = logging.getLogger(__name__)

_scheme = HTTPBearer(auto_error=False)


def _configured_token() -> str:
    return (settings.FUNDAMENTALS_INGEST_TOKEN or "").strip()


async def require_ingest_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_scheme),
) -> None:
    """Authorize a machine ingestion call, or raise.

    Never echoes the presented token - not in the response, not in the log line. A rejected
    call is logged as a bare count-worthy event so a misconfigured job is visible without
    the secret leaking into Railway's log stream.
    """
    expected = _configured_token()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "ingest_unavailable", "reason": "ingest_token_not_configured"},
        )
    presented = (credentials.credentials or "") if credentials else ""
    scheme_ok = bool(credentials) and (credentials.scheme or "").lower() == "bearer"
    # compare_digest on both branches: a missing token must not return faster than a wrong
    # one. The dummy keeps the comparison running when nothing was presented at all.
    if not hmac.compare_digest(presented or "\x00", expected) or not scheme_ok:
        logger.warning("Fundamentals ingest rejected: bad or missing bearer token.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "unauthorized", "reason": "bad_ingest_token"},
            headers={"WWW-Authenticate": "Bearer"},
        )
