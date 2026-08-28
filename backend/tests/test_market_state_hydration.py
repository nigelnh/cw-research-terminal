import asyncio
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any
import pytest

from app.market_data.market_schemas import CanonicalQuote
from app.market_data.market_state import MarketState
from app.market_data.market_state_store import MarketStateStore, NullMarketStateStore
from app.market_data.market_subscription_manager import SubscriptionManager
from app.market_data.market_session import VN_TZ, market_session
from app.market_data.providers.base_market_provider import MarketDataProvider


class MockStore(MarketStateStore):
    def __init__(self, initial_data: Optional[Dict[str, CanonicalQuote]] = None):
        self._data: Dict[str, CanonicalQuote] = initial_data or {}
        self.available = True

    def is_available(self) -> bool:
        return self.available

    async def initialize(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def load(self, symbol: str) -> Optional[CanonicalQuote]:
        return self._data.get(symbol.upper())

    async def load_many(self, symbols: List[str]) -> Dict[str, CanonicalQuote]:
        return {s.upper(): self._data[s.upper()] for s in symbols if s.upper() in self._data}

    async def save(self, symbol: str, quote: CanonicalQuote) -> None:
        self._data[symbol.upper()] = quote.model_copy()

    async def save_many(self, quotes: Dict[str, CanonicalQuote]) -> None:
        for s, q in quotes.items():
            self._data[s.upper()] = q.model_copy()

    async def delete(self, symbol: str) -> None:
        self._data.pop(symbol.upper(), None)

    def enqueue_save(self, symbol: str, quote: CanonicalQuote) -> None:
        self._data[symbol.upper()] = quote.model_copy()

    async def health(self) -> Dict[str, Any]:
        return {"market_cache_available": self.available}


class MockProvider(MarketDataProvider):
    def __init__(self):
        super().__init__()
        self.active_subs: List[str] = []
        self.callback = None

    def set_event_callback(self, callback) -> None:
        self.callback = callback

    def get_active_subscriptions(self) -> List[str]:
        return self.active_subs

    def get_health(self) -> Dict[str, Any]:
        return {"upstream_status": self._upstream_status}

    async def connect(self) -> bool:
        self._upstream_status = "CONNECTED"
        return True

    async def disconnect(self) -> None:
        self._upstream_status = "DISCONNECTED"

    async def set_subscriptions(self, symbols: List[str]) -> bool:
        self.active_subs = list(symbols)
        return True

    async def get_historical_bars(self, *args, **kwargs):
        return []


@pytest.mark.asyncio
async def test_same_session_warm_cache_populates_initial_market_state():
    """Same-session warm cache populates initial MarketState before a new realtime tick arrives."""
    state = MarketState()
    now_dt = market_session.get_vn_now()
    now_ms = int(now_dt.timestamp() * 1000)

    cached_quote = CanonicalQuote(
        symbol="HPG",
        instrument_type="STOCK",
        last_price=22200.0,
        total_volume=1429000,
        bid1_price=22150.0,
        ask1_price=22200.0,
        reference_price=22250.0,
        received_timestamp=now_ms,
        source_timestamp=now_ms,
    )
    store = MockStore({"HPG": cached_quote})
    provider = MockProvider()
    mgr = SubscriptionManager(provider=provider, state=state, store=store)

    assert not state.has_quote("HPG")

    restored = await mgr.hydrate_missing_market_state(["HPG"])
    assert "HPG" in restored
    assert state.has_quote("HPG")

    q = state.get_quote("HPG")
    assert q is not None
    assert q.last_price == 22200.0
    assert q.total_volume == 1429000
    assert q.bid1_price == 22150.0
    assert q.ask1_price == 22200.0


@pytest.mark.asyncio
async def test_later_signalr_tick_supersedes_hydrated_state():
    """Later SignalR tick supersedes hydrated state with updated price and volume."""
    state = MarketState()
    now_dt = market_session.get_vn_now()
    now_ms = int(now_dt.timestamp() * 1000)

    cached_quote = CanonicalQuote(
        symbol="HPG",
        instrument_type="STOCK",
        last_price=22200.0,
        total_volume=1429000,
        received_timestamp=now_ms - 10000,
        source_timestamp=now_ms - 10000,
    )
    store = MockStore({"HPG": cached_quote})
    provider = MockProvider()
    mgr = SubscriptionManager(provider=provider, state=state, store=store)

    await mgr.hydrate_missing_market_state(["HPG"])
    q_initial = state.get_quote("HPG")
    assert q_initial is not None
    assert q_initial.last_price == 22200.0

    # Incoming live trade tick via SignalR
    raw_trade = {
        "Ticker": "HPG",
        "Close": 22350.0,
        "Total_Vol": 1500000,
        "ReferencePrice": 22250.0,
    }
    mgr._on_provider_event("trade", raw_trade, "HPG")

    updated = state.get_quote("HPG")
    assert updated is not None
    assert updated.last_price == 22350.0
    assert updated.total_volume == 1500000


@pytest.mark.asyncio
async def test_delayed_stale_redis_hydration_cannot_overwrite_newer_realtime_tick():
    """Delayed/stale Redis hydration cannot overwrite a newer realtime tick in memory."""
    state = MarketState()
    now_dt = market_session.get_vn_now()
    now_ms = int(now_dt.timestamp() * 1000)

    # Realtime trade arrives first at t = now_ms
    state.apply_trade_event({
        "Ticker": "HPG",
        "Close": 22500.0,
        "Total_Vol": 2000000,
    })
    q_live = state.get_quote("HPG")
    assert q_live is not None
    assert q_live.last_price == 22500.0

    # Old stale cache from t = now_ms - 60000 arrives late
    stale_quote = CanonicalQuote(
        symbol="HPG",
        instrument_type="STOCK",
        last_price=22000.0,
        total_volume=1000000,
        received_timestamp=now_ms - 60000,
        source_timestamp=now_ms - 60000,
    )
    store = MockStore({"HPG": stale_quote})
    provider = MockProvider()
    mgr = SubscriptionManager(provider=provider, state=state, store=store)

    restored = await mgr.hydrate_missing_market_state(["HPG"])
    assert restored == []  # Not missing, and even if attempted, rejected by timestamp

    # In-memory quote remains protected at 22500.0
    q_protected = state.get_quote("HPG")
    assert q_protected is not None
    assert q_protected.last_price == 22500.0


@pytest.mark.asyncio
async def test_same_session_last_price_and_cumulative_volume_survive_backend_restart():
    """Same-session last price and cumulative volume survive backend restart when warm cache provides them."""
    state_after_restart = MarketState()
    now_dt = market_session.get_vn_now()
    now_ms = int(now_dt.timestamp() * 1000)

    cached_quote = CanonicalQuote(
        symbol="NVL",
        instrument_type="STOCK",
        last_price=13150.0,
        total_volume=440400,
        bid1_price=13150.0,
        ask1_price=13200.0,
        reference_price=13200.0,
        received_timestamp=now_ms - 5000,
        source_timestamp=now_ms - 5000,
    )
    store = MockStore({"NVL": cached_quote})
    provider = MockProvider()
    mgr = SubscriptionManager(provider=provider, state=state_after_restart, store=store)

    assert state_after_restart.get_quote("NVL") is None
    await mgr.hydrate_missing_market_state(["NVL"])

    restored_q = state_after_restart.get_quote("NVL")
    assert restored_q is not None
    assert restored_q.last_price == 13150.0
    assert restored_q.total_volume == 440400


@pytest.mark.asyncio
async def test_previous_session_last_volume_not_presented_as_today_session_state():
    """Previous-session last/volume are not presented as today's live session state."""
    state = MarketState()
    # Timestamp from yesterday (24 hours ago)
    yesterday_dt = market_session.get_vn_now() - timedelta(days=1, hours=2)
    yesterday_ms = int(yesterday_dt.timestamp() * 1000)

    yesterday_quote = CanonicalQuote(
        symbol="HPG",
        instrument_type="STOCK",
        last_price=22200.0,
        total_volume=1429000,
        bid1_price=22150.0,
        ask1_price=22200.0,
        reference_price=22250.0,
        received_timestamp=yesterday_ms,
        source_timestamp=yesterday_ms,
    )
    store = MockStore({"HPG": yesterday_quote})
    provider = MockProvider()
    mgr = SubscriptionManager(provider=provider, state=state, store=store)

    await mgr.hydrate_missing_market_state(["HPG"])

    q = state.get_quote("HPG")
    assert q is not None
    # Intraday trade and volume from yesterday MUST be sanitized to None
    assert q.last_price is None
    assert q.total_volume is None
    assert q.bid1_price is None
    assert q.ask1_price is None
    # Safe reference data is preserved
    assert q.reference_price == 22250.0


@pytest.mark.asyncio
async def test_bid_ask_only_warm_data_never_fabricates_last_price():
    """Bid/ask-only warm data never fabricates a last price."""
    state = MarketState()
    now_dt = market_session.get_vn_now()
    now_ms = int(now_dt.timestamp() * 1000)

    ba_quote = CanonicalQuote(
        symbol="CHPG2541",
        instrument_type="CW",
        last_price=None,  # No trades today
        total_volume=None,
        bid1_price=320.0,
        ask1_price=330.0,
        received_timestamp=now_ms,
        source_timestamp=now_ms,
    )
    store = MockStore({"CHPG2541": ba_quote})
    provider = MockProvider()
    mgr = SubscriptionManager(provider=provider, state=state, store=store)

    await mgr.hydrate_missing_market_state(["CHPG2541"])

    q = state.get_quote("CHPG2541")
    assert q is not None
    assert q.bid1_price == 320.0
    assert q.ask1_price == 330.0
    assert q.last_price is None  # Strictly None, never 325.0 midpoint


@pytest.mark.asyncio
async def test_null_store_leaves_application_operational():
    """Null / unavailable Redis store leaves the application fully operational."""
    state = MarketState()
    provider = MockProvider()
    mgr = SubscriptionManager(provider=provider, state=state, store=NullMarketStateStore())

    restored = await mgr.hydrate_missing_market_state(["HPG"])
    assert restored == []

    # Live SignalR ticks continue to work normally
    mgr._on_provider_event("trade", {"Ticker": "HPG", "Close": 22400.0}, "HPG")
    q_final = state.get_quote("HPG")
    assert q_final is not None
    assert q_final.last_price == 22400.0
