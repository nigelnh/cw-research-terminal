"""Sparsely-traded CWs get today's trade group seeded from the snapshot poll,
but a fresher live Trading_Data_Stream tick is never overwritten."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from app.market_data.market_state import MarketState
from app.market_data.market_state_store import NullMarketStateStore
from app.market_data.market_subscription_manager import SubscriptionManager
from app.market_data.session_reference import reference_session_date
from tests.fixtures.mock_market_provider import MockMarketDataProvider

pytestmark = pytest.mark.asyncio


class _SnapshotProvider(MockMarketDataProvider):
    def __init__(self, rows):
        super().__init__(max_symbols=33)
        self._rows = rows
        self.calls = 0

    async def get_session_trade_snapshot(self, symbols, session_date):
        self.calls += 1
        return {s: self._rows[s] for s in symbols if s in self._rows}


def _manager(provider):
    mgr = SubscriptionManager(
        provider=provider, state=MarketState(), store=NullMarketStateStore(), max_symbols=33,
    )
    mgr._server_owned = True
    mgr._server_universe_symbols = {"CHPG2627"}
    return mgr


async def test_poll_seeds_trade_group_for_a_flat_cw():
    today = reference_session_date().isoformat()
    provider = _SnapshotProvider({
        "CHPG2627": {
            "last_price": 1090.0, "open_price": 1130.0, "high_price": 1130.0,
            "low_price": 1090.0, "total_volume": 535100.0, "trading_value": 593146000.0,
            "reference_price": 1100.0, "as_of": f"{today} 10:28",
        }
    })
    mgr = _manager(provider)
    patches: list[dict] = []
    mgr.register_patch_listener(patches.append)

    await mgr._poll_session_trades()

    quote = mgr.state.get_quote("CHPG2627")
    assert quote is not None
    assert quote.last_price == 1090.0
    assert quote.total_volume == 535100
    assert quote.trading_value == 593146000.0
    assert any(m["symbol"] == "CHPG2627" and "Traded" in m["patch"] for m in patches)


async def test_poll_does_not_overwrite_a_fresher_live_tick():
    today = reference_session_date().isoformat()
    mgr = _manager(_SnapshotProvider({
        "CHPG2627": {
            "last_price": 1090.0, "total_volume": 500000.0, "trading_value": 1.0,
            "reference_price": 1100.0, "as_of": f"{today} 10:28",
        }
    }))
    # A live tick at 10:55 already updated the trade group.
    mgr.state.apply_trade_event({
        "Ticker": "CHPG2627", "Close": 1120.0, "Reference": 1100.0,
        "TotalMatchVolume": 700000, "TradingDate": f"{today} 10:55",
    })

    await mgr._poll_session_trades()

    quote = mgr.state.get_quote("CHPG2627")
    assert quote.last_price == 1120.0        # the live tick wins
    assert quote.total_volume == 700000
