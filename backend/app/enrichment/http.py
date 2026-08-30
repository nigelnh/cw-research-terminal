"""Shared bounded HTTP client for enrichment source fetches.

Small, dependency-light wrapper over httpx:
  * fixed connect/read timeout,
  * bounded exponential-backoff retry on transient failures / 429 / 5xx,
  * a benign, honest User-Agent (no browser spoofing, no bot-wall evasion),
  * a SourceFetchLog row per attempt when a DB sessionmaker is supplied.

Never used from the request path — only from CLI ingestion entrypoints.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import settings
from app.persistence.models import SourceFetchLog

logger = logging.getLogger("app.enrichment.http")

USER_AGENT = "cw-research-terminal/1.0 (+https://github.com/nigelnh/cw-research-terminal)"

_TRANSIENT_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


class SourceFetchError(RuntimeError):
    """A source fetch exhausted its retries or returned a non-retryable error."""


@dataclass(slots=True)
class FetchResult:
    status: int
    json: Any
    duration_ms: int


class EnrichmentHttpClient:
    def __init__(
        self,
        *,
        base_headers: dict[str, str] | None = None,
        sessionmaker: async_sessionmaker | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
    ) -> None:
        self._headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        if base_headers:
            self._headers.update(base_headers)
        self._sm = sessionmaker
        self._timeout = float(timeout if timeout is not None else settings.ENRICHMENT_HTTP_TIMEOUT_SECONDS)
        self._max_retries = int(max_retries if max_retries is not None else settings.ENRICHMENT_HTTP_MAX_RETRIES)
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "EnrichmentHttpClient":
        self._client = httpx.AsyncClient(
            headers=self._headers,
            timeout=httpx.Timeout(self._timeout, connect=min(self._timeout, 10.0)),
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def get_json(
        self,
        url: str,
        *,
        source: str,
        endpoint: str,
        symbol: str | None = None,
        params: dict[str, Any] | None = None,
        item_count_fn=None,
    ) -> FetchResult:
        assert self._client is not None, "use inside `async with`"
        started = time.monotonic()
        last_err: str | None = None
        status_code: int | None = None
        for attempt in range(self._max_retries + 1):
            try:
                resp = await self._client.get(url, params=params)
                status_code = resp.status_code
                if status_code in _TRANSIENT_STATUS:
                    last_err = f"HTTP {status_code}"
                    raise _Retry(last_err)
                resp.raise_for_status()
                data = resp.json()
                dur = int((time.monotonic() - started) * 1000)
                count = 0
                try:
                    count = int(item_count_fn(data)) if item_count_fn else 0
                except Exception:  # noqa: BLE001
                    count = 0
                await self._log(source, endpoint, symbol, status_code, count, True, None, dur)
                return FetchResult(status=status_code, json=data, duration_ms=dur)
            except _Retry as r:
                last_err = str(r)
            except httpx.HTTPStatusError as e:
                last_err = f"HTTP {e.response.status_code}"
                status_code = e.response.status_code
                break  # non-transient status -> do not retry
            except (httpx.TransportError, ValueError) as e:
                last_err = f"{type(e).__name__}: {e}"
            if attempt < self._max_retries:
                await asyncio.sleep(min(2.0 * (2 ** attempt), 15.0))

        dur = int((time.monotonic() - started) * 1000)
        await self._log(source, endpoint, symbol, status_code, 0, False, last_err, dur)
        raise SourceFetchError(f"{source}/{endpoint} failed: {last_err}")

    async def _log(
        self,
        source: str,
        endpoint: str,
        symbol: str | None,
        http_status: int | None,
        item_count: int,
        ok: bool,
        error: str | None,
        duration_ms: int,
    ) -> None:
        if self._sm is None:
            return
        try:
            async with self._sm() as s:
                s.add(
                    SourceFetchLog(
                        source=source,
                        endpoint=endpoint[:120],
                        symbol=(symbol or None),
                        http_status=http_status,
                        item_count=item_count,
                        ok=ok,
                        error=(error[:1000] if error else None),
                        duration_ms=duration_ms,
                    )
                )
                await s.commit()
        except Exception as e:  # noqa: BLE001 - observability must never break ingestion
            logger.warning("source_fetch_log write failed: %s", e)


class _Retry(RuntimeError):
    pass
