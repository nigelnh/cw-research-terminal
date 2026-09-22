"""An empty upstream answer is an answer, and the universe is warmed off the request path.

Measured on production: the first read of a symbol each day took 20.4s and the second 0.25s.
The 20.4s was not the chart and not the 63KB of bars - it was `HISTORY_GAPFILL_LOCK_WAIT_
SECONDS` (25s) spent waiting for one of two global gap-fill slots, after which the request
was served a DB partial anyway. One log window held 325 `gap-fill deferred` lines.

What held the slots was retries that could not succeed:

  CFPT2617 1d 2026-09-21..2026-09-22: attempt 1/5 ... 5/5 - backing off 25.9s
    "Vnstock returned no usable historical data"

vnstock raises `ValueError: Dữ liệu trống cho mã CFPT2617 với interval 1D.` there. It is
the truth: that warrant did not trade on those two days - the SAME symbol over
2026-09-01..2026-09-22 returns ten rows. The catch-all turned it into
`HistoricalUpstreamError`, which is retryable, so each one held a slot for ~30s.
"""
from datetime import date

import pytest

from app.market_data.market_schemas import (
    HistoricalNoDataError,
    HistoricalTransportError,
    HistoricalUpstreamError,
)
from app.persistence.ingestion.retry import classify, is_retryable


# --------------------------------------------------------------------------- #
# Classification
# --------------------------------------------------------------------------- #
def test_no_data_is_permanent_for_this_request():
    """Retrying identical parameters cannot turn an empty window into bars."""
    assert is_retryable(HistoricalNoDataError("empty")) is False
    assert classify(HistoricalNoDataError("empty")) == "NO_DATA"


def test_a_genuine_upstream_fault_still_retries():
    """The fix must not make real transient failures permanent."""
    assert is_retryable(HistoricalUpstreamError("502")) is True
    assert is_retryable(HistoricalTransportError("timeout")) is True


@pytest.mark.asyncio
async def test_a_value_error_from_the_fetcher_is_classified_as_no_data():
    """vnstock signals an empty frame with ValueError, and uses it for a rejected parameter
    too. Neither is fixed by asking again, and matching the TYPE rather than its Vietnamese
    message keeps this working when the library rewords it."""
    from app.market_data.providers.vnstock_provider import VnstockProvider

    def _empty(*_args, **_kw):
        raise ValueError("Dữ liệu trống cho mã CFPT2617 với interval 1D.")

    p = VnstockProvider(history_fetcher=_empty)
    with pytest.raises(HistoricalNoDataError) as err:
        await p.get_historical_bars("CFPT2617", "1D", "2026-09-21", "2026-09-22", adjusted=False)
    assert "CFPT2617" in str(err.value)


@pytest.mark.asyncio
async def test_a_transport_failure_is_still_a_transport_failure():
    from app.market_data.providers.vnstock_provider import VnstockProvider

    def _down(*_args, **_kw):
        raise RuntimeError("connection error: upstream_unavailable")

    p = VnstockProvider(history_fetcher=_down)
    with pytest.raises(HistoricalTransportError):
        await p.get_historical_bars("HPG", "1D", "2026-09-01", "2026-09-22", adjusted=False)


# --------------------------------------------------------------------------- #
# The read path answers rather than erroring
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_an_empty_window_is_served_as_an_empty_series_not_a_fault():
    """`GET /history` fell through to a bare `except Exception` that would have made this a
    500. An empty series is the honest answer: the provider is healthy and holds nothing."""
    from fastapi.testclient import TestClient
    from unittest.mock import AsyncMock, patch

    from app.main import app

    with patch(
        "app.market_data.market_router.history_read_service.get_history",
        new=AsyncMock(side_effect=HistoricalNoDataError("nothing for CFPT2617")),
    ), TestClient(app) as client:
        r = client.get("/api/market/history/CFPT2617?timeframe=1D&adjusted=false")

    assert r.status_code == 200, "an empty answer must not be reported as a server fault"
    assert r.json() == []


@pytest.mark.asyncio
async def test_a_real_outage_still_surfaces_as_503():
    from fastapi.testclient import TestClient
    from unittest.mock import AsyncMock, patch

    from app.main import app

    with patch(
        "app.market_data.market_router.history_read_service.get_history",
        new=AsyncMock(side_effect=HistoricalTransportError("upstream down")),
    ), TestClient(app) as client:
        r = client.get("/api/market/history/HPG?timeframe=1D&adjusted=false")

    assert r.status_code == 503


# --------------------------------------------------------------------------- #
# The warm pass
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_the_warm_pass_declines_outside_postgres_first():
    """Provider-direct mode has no table to warm; it must not start calling upstream."""
    from app.market_data.history_read_service import HistoryReadService

    svc = HistoryReadService()
    out = await svc.warm_universe(["HPG", "FPT"])
    assert out.get("skipped")
