"""The reference-refresh retry loop must recognize "done" using only what its source
(``get_session_reference_data``) can actually supply — ceiling/floor never arrives for a
CW that way (the provider has no CW band endpoint; those come from the snapshot resolver
deriving them from the underlying instead, a separate path). Requiring them here would
keep the loop retrying the full universe every 30s forever, since it could never succeed."""

from __future__ import annotations

import pytest

from app.market_data.market_state import MarketState
from app.market_data.market_state_store import NullMarketStateStore
from app.market_data.market_subscription_manager import SubscriptionManager
from tests.fixtures.mock_market_provider import MockMarketDataProvider

pytestmark = pytest.mark.asyncio

SESSION = "2026-09-04"


def _manager(symbols):
    mgr = SubscriptionManager(
        provider=MockMarketDataProvider(max_symbols=33), state=MarketState(),
        store=NullMarketStateStore(), max_symbols=33,
    )
    mgr._server_universe_symbols = set(symbols)
    return mgr


async def test_a_cw_with_only_a_reference_price_counts_as_complete():
    mgr = _manager(["HPG", "CHPG2617"])
    mgr.state.apply_reference_metadata("HPG", session_date=SESSION,
                                        reference_price=21600, ceiling_price=23100, floor_price=20100)
    mgr.state.apply_reference_metadata("CHPG2617", session_date=SESSION, reference_price=440)
    assert mgr._reference_metadata_complete(SESSION) is True


async def test_a_cw_with_no_reference_price_yet_is_still_incomplete():
    mgr = _manager(["HPG", "CHPG2617"])
    mgr.state.apply_reference_metadata("HPG", session_date=SESSION,
                                        reference_price=21600, ceiling_price=23100, floor_price=20100)
    assert mgr._reference_metadata_complete(SESSION) is False


async def test_a_stock_missing_bands_is_still_incomplete():
    """The relaxation is CW-specific — stocks really do get bands from this source, and
    a stock silently missing them should keep retrying."""
    mgr = _manager(["HPG", "CHPG2617"])
    mgr.state.apply_reference_metadata("HPG", session_date=SESSION, reference_price=21600)  # no bands
    mgr.state.apply_reference_metadata("CHPG2617", session_date=SESSION, reference_price=440)
    assert mgr._reference_metadata_complete(SESSION) is False


async def test_an_all_cw_universe_completes_and_stops_the_retry_loop():
    mgr = _manager(["CHPG2617", "CHPG2618"])
    mgr.state.apply_reference_metadata("CHPG2617", session_date=SESSION, reference_price=440)
    mgr.state.apply_reference_metadata("CHPG2618", session_date=SESSION, reference_price=380)
    assert mgr._reference_metadata_complete(SESSION) is True
