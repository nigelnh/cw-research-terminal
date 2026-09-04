import json
import pytest
import asyncio
import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from app.main import app
from app.market_data.market_schemas import CanonicalQuote, HistoricalBar
from app.market_data.market_state import MarketState, market_state
from app.market_data.market_session import market_session
from app.market_data.market_state_store import NullMarketStateStore
from app.market_data.redis_market_state_store import RedisMarketStateStore
from app.market_data.market_subscription_manager import SubscriptionManager, subscription_manager
from tests.fixtures.mock_market_provider import MockMarketDataProvider
from app.instruments.instrument_registry import instrument_registry

client = TestClient(app)


class MockRedisClient:
    """In-memory dictionary-backed async redis double for testing RedisMarketStateStore."""

    def __init__(self):
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.should_fail = False

    async def ping(self):
        if self.should_fail:
            raise ConnectionError("Redis connection failed")
        return True

    async def get(self, key: str):
        if self.should_fail:
            raise ConnectionError("Redis GET failed")
        return self.store.get(key)

    async def mget(self, keys: list[str]):
        if self.should_fail:
            raise ConnectionError("Redis MGET failed")
        return [self.store.get(k) for k in keys]

    async def set(self, key: str, val: str, ex: int | None = None):
        if self.should_fail:
            raise ConnectionError("Redis SET failed")
        self.store[key] = val
        if ex:
            self.ttls[key] = ex
        return True

    async def delete(self, key: str):
        if self.should_fail:
            raise ConnectionError("Redis DELETE failed")
        self.store.pop(key, None)
        self.ttls.pop(key, None)
        return True

    def pipeline(self):
        return MockRedisPipeline(self)

    async def aclose(self):
        pass


class MockRedisPipeline:
    def __init__(self, parent: MockRedisClient):
        self.parent = parent
        self.commands = []

    def set(self, key: str, val: str, ex: int | None = None):
        self.commands.append(("set", key, val, ex))
        return self

    async def execute(self):
        if self.parent.should_fail:
            raise ConnectionError("Redis Pipeline execution failed")
        for cmd in self.commands:
            if cmd[0] == "set":
                self.parent.store[cmd[1]] = cmd[2]
                if cmd[3]:
                    self.parent.ttls[cmd[1]] = cmd[3]
        return [True] * len(self.commands)


@pytest.mark.asyncio
async def test_overview_redis_cache_preserves_observation_time_across_restart():
    redis = MockRedisClient()
    first = RedisMarketStateStore(enabled=True, redis_client=redis)
    await first.initialize()
    saved = {"cached_at": 1234.5, "payload": {
        "indices": [{"symbol": "VNINDEX", "value": 1200, "volume": 0,
                     "trading_value": None, "as_of": "2026-09-03"}],
        "top_stock_volume": [], "top_cw_volume": [],
    }}
    await first.save_market_overview(saved)
    await first.close()
    restarted = RedisMarketStateStore(enabled=True, redis_client=redis)
    await restarted.initialize()
    try:
        assert await restarted.load_market_overview() == saved
        assert redis.ttls[first.OVERVIEW_KEY] == 7 * 86400
        assert await restarted.load("VNINDEX") is None
    finally:
        await restarted.close()


@pytest.mark.asyncio
async def test_dashboard_history_cache_preserves_basis_session_and_missing_values():
    store = RedisMarketStateStore(enabled=True, redis_client=MockRedisClient())
    await store.initialize()
    try:
        bars = [HistoricalBar(
            date="2026-09-03", session_date="2026-09-03", open=440, high=490,
            low=420, close=440, volume=0, value=None, price_basis="RAW", adjusted=False,
        )]
        await store.save_dashboard_history("CHPG2617", "RAW", "2026-09-03", bars)
        restored = await store.load_dashboard_history("CHPG2617", "RAW", "2026-09-03")
        assert restored == bars
        assert restored[0].volume == 0
        assert restored[0].value is None
        assert await store.load_dashboard_history("CHPG2617", "ADJUSTED", "2026-09-03") is None
        assert await store.load_dashboard_history("CHPG2617", "RAW", "2026-09-04") is None
        assert await store.load("CHPG2617") is None  # never enters live CanonicalQuote namespace
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_redis_initialize_never_logs_connection_url(caplog):
    secret_url = "redis://default:private-password@redis.internal:6379/0"
    store = RedisMarketStateStore(
        redis_url=secret_url,
        enabled=True,
        redis_client=MockRedisClient(),
    )

    with caplog.at_level("INFO", logger="app.market_data.redis_market_state_store"):
        await store.initialize()
    try:
        assert "private-password" not in caplog.text
        assert secret_url not in caplog.text
        assert "Connected to Redis Warm Market State Cache." in caplog.text
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_null_market_state_store():
    store = NullMarketStateStore()
    assert store.is_available() is False
    assert await store.load("HPG") is None
    assert await store.load_many(["HPG", "VHM"]) == {}
    health = await store.health()
    assert health["redis_enabled"] is False
    assert health["market_cache_available"] is False


@pytest.mark.asyncio
async def test_redis_market_state_store_save_load_preserves_canonical_units():
    mock_client = MockRedisClient()
    store = RedisMarketStateStore(
        enabled=True,
        ttl_seconds=3600,
        max_staleness_seconds=86400,
        redis_client=mock_client,
    )
    await store.initialize()
    assert store.is_available() is True

    # 1. Test Stock Quote in Raw VND (21850.0)
    now_ms = int(time.time() * 1000)
    stock_quote = CanonicalQuote(
        symbol="HPG",
        instrument_type="STOCK",
        last_price=21850.0,
        reference_price=21800.0,
        bid1_price=21850.0,
        bid1_quantity=100000,
        ask1_price=21900.0,
        ask1_quantity=50000,
        price_change=50.0,
        price_change_percent=0.0023,
        total_volume=12500000,
        received_timestamp=now_ms,
        source_timestamp=now_ms,
    )

    await store.save("HPG", stock_quote)
    key = "cw_research:market_state:v1:HPG"
    assert key in mock_client.store
    assert mock_client.ttls[key] == 3600

    loaded_stock = await store.load("HPG")
    assert loaded_stock is not None
    assert loaded_stock.symbol == "HPG"
    assert loaded_stock.instrument_type == "STOCK"
    # Exact canonical Raw VND unit preservation (NOT scaled to 21.85)
    assert loaded_stock.last_price == 21850.0
    assert loaded_stock.bid1_price == 21850.0
    assert loaded_stock.ask1_price == 21900.0
    assert loaded_stock.price_change == 50.0
    assert loaded_stock.price_change_percent == 0.0023

    # 2. Test Index Quote in Points (1280.5)
    index_quote = CanonicalQuote(
        symbol="VNINDEX",
        instrument_type="INDEX",
        last_price=1280.5,
        reference_price=1275.0,
        total_volume=500000000,
        received_timestamp=now_ms,
        source_timestamp=now_ms,
    )
    await store.save("VNINDEX", index_quote)
    loaded_index = await store.load("VNINDEX")
    assert loaded_index is not None
    assert loaded_index.instrument_type == "INDEX"
    assert loaded_index.last_price == 1280.5

    # 3. Test CW Quote in Raw VND (1810.0)
    cw_quote = CanonicalQuote(
        symbol="CVHM2615",
        instrument_type="CW",
        underlying_symbol="VHM",
        bid1_price=1810.0,
        bid1_quantity=5000,
        ask1_price=1840.0,
        ask1_quantity=8000,
        last_price=None,  # No trade
        received_timestamp=now_ms,
        source_timestamp=now_ms,
    )
    await store.save("CVHM2615", cw_quote)
    loaded_cw = await store.load("CVHM2615")
    assert loaded_cw is not None
    assert loaded_cw.symbol == "CVHM2615"
    assert loaded_cw.bid1_price == 1810.0
    assert loaded_cw.ask1_price == 1840.0
    assert loaded_cw.last_price is None

    # 4. Test Batch Load
    loaded_many = await store.load_many(["HPG", "VNINDEX", "CVHM2615"])
    assert len(loaded_many) == 3
    assert loaded_many["HPG"].last_price == 21850.0
    assert loaded_many["VNINDEX"].last_price == 1280.5
    assert loaded_many["CVHM2615"].bid1_price == 1810.0

    await store.close()


@pytest.mark.asyncio
async def test_redis_accepts_fresh_reference_only_quote_without_promoting_it_to_live():
    mock_client = MockRedisClient()
    store = RedisMarketStateStore(
        enabled=True,
        ttl_seconds=3600,
        max_staleness_seconds=3600,
        redis_client=mock_client,
    )
    await store.initialize()
    now_ms = int(time.time() * 1000)
    quote = CanonicalQuote(
        symbol="HPG",
        reference_price=22_200,
        ceiling_price=23_750,
        floor_price=20_650,
        reference_session_date=datetime.now(timezone.utc).date().isoformat(),
        reference_timestamp=now_ms,
        received_timestamp=0,
    )

    await store.save("HPG", quote)
    loaded = await store.load("HPG")

    assert loaded is not None
    assert loaded.reference_price == 22_200
    assert loaded.received_timestamp == 0
    await store.close()


@pytest.mark.asyncio
async def test_redis_market_state_store_staleness_rejection():
    mock_client = MockRedisClient()
    store = RedisMarketStateStore(
        enabled=True,
        ttl_seconds=3600,
        max_staleness_seconds=60,  # 60 seconds max age
        redis_client=mock_client,
    )
    await store.initialize()

    # Create stale quote (2 hours ago)
    stale_ts = int((time.time() - 7200) * 1000)
    stale_quote = CanonicalQuote(
        symbol="HPG",
        last_price=21850.0,
        received_timestamp=stale_ts,
        source_timestamp=stale_ts,
    )
    await store.save("HPG", stale_quote)

    # Attempt to load: must be rejected due to staleness policy
    loaded = await store.load("HPG")
    assert loaded is None

    loaded_many = await store.load_many(["HPG"])
    assert loaded_many == {}

    await store.close()


@pytest.mark.asyncio
async def test_default_ttl_and_staleness_survive_a_weekend_without_a_new_tick():
    """The 24h defaults used to quietly erase the whole watchlist on any restart landing
    more than a day after Friday's last write - not just an ordinary ~66h weekend gap, and
    especially Tet, when HOSE can close for ~9 consecutive days. Uses the real
    `settings.MARKET_STATE_CACHE_TTL_SECONDS` / `MARKET_STATE_MAX_STALENESS_SECONDS`
    defaults (no override), so this pins the actual production configuration."""
    mock_client = MockRedisClient()
    store = RedisMarketStateStore(enabled=True, redis_client=mock_client)
    await store.initialize()

    # Friday's last tick before the close, restored on a hypothetical Monday-morning
    # restart ~70 hours later - well past the old 24h defaults, comfortably inside a
    # normal weekend.
    friday_close_ts = int((time.time() - 70 * 3600) * 1000)
    quote = CanonicalQuote(
        symbol="HPG", last_price=21850.0,
        received_timestamp=friday_close_ts, source_timestamp=friday_close_ts,
    )
    await store.save("HPG", quote)

    key = "cw_research:market_state:v1:HPG"
    assert mock_client.ttls[key] > 9 * 86400  # comfortably survives a ~9-day Tet closure

    loaded = await store.load("HPG")
    assert loaded is not None
    assert loaded.last_price == 21850.0

    loaded_many = await store.load_many(["HPG"])
    assert loaded_many["HPG"].last_price == 21850.0

    await store.close()


@pytest.mark.asyncio
async def test_redis_failure_graceful_degradation():
    mock_client = MockRedisClient()
    store = RedisMarketStateStore(
        enabled=True,
        ttl_seconds=3600,
        max_staleness_seconds=86400,
        redis_client=mock_client,
    )
    await store.initialize()
    assert store.is_available() is True

    # Simulate Redis failure
    mock_client.should_fail = True

    # Load operations must not crash and degrade to None / {}
    assert await store.load("HPG") is None
    assert await store.load_many(["HPG", "VHM"]) == {}

    # Save operations must not raise
    quote = CanonicalQuote(symbol="HPG", last_price=21850.0)
    await store.save("HPG", quote)
    await store.save_many({"HPG": quote})

    # Health reflects disconnection
    health = await store.health()
    assert health["redis_connected"] is False
    assert health["market_cache_available"] is False

    await store.close()


@pytest.mark.asyncio
async def test_redis_health_counts_successful_quote_writes_and_unique_restores():
    mock_client = MockRedisClient()
    store = RedisMarketStateStore(
        enabled=True,
        ttl_seconds=3600,
        max_staleness_seconds=86400,
        redis_client=mock_client,
    )
    await store.initialize()
    now_ms = int(time.time() * 1000)
    hpg = CanonicalQuote(symbol="HPG", last_price=21_850.0, received_timestamp=now_ms)
    vhm = CanonicalQuote(symbol="VHM", last_price=58_000.0, received_timestamp=now_ms)

    await store.save("HPG", hpg)
    await store.save_many({"HPG": hpg, "VHM": vhm})
    assert await store.load("HPG") == hpg
    loaded = await store.load_many(["HPG", " hpg ", "VHM", "MISSING"])
    assert set(loaded) == {"HPG", "VHM"}

    health = await store.health()
    assert health["counters"] == {
        "writes_succeeded": 3,
        "quotes_restored": 3,
        "write_errors": 0,
        "restore_errors": 0,
        "connection_restores": 0,
    }
    await store.close()


@pytest.mark.asyncio
async def test_redis_health_counts_errors_and_connectivity_restores_without_payloads():
    mock_client = MockRedisClient()
    store = RedisMarketStateStore(enabled=True, redis_client=mock_client)
    await store.initialize()
    now_ms = int(time.time() * 1000)
    quote = CanonicalQuote(symbol="HPG", last_price=21_850.0, received_timestamp=now_ms)

    mock_client.store[store._get_key("BAD")] = "not-json"
    assert await store.load("BAD") is None
    assert store.is_available() is True

    mock_client.should_fail = True
    await store.save("HPG", quote)
    assert store.is_available() is False
    mock_client.should_fail = False
    assert (await store.health())["redis_connected"] is True

    mock_client.should_fail = True
    assert await store.load_many(["HPG"]) == {}
    mock_client.should_fail = False
    health = await store.health()

    assert health["counters"] == {
        "writes_succeeded": 0,
        "quotes_restored": 0,
        "write_errors": 1,
        "restore_errors": 2,
        "connection_restores": 2,
    }
    assert all(isinstance(value, int) for value in health["counters"].values())
    await store.close()


@pytest.mark.asyncio
async def test_browser_reconnect_receives_in_memory_market_state_immediately():
    """
    Asserts that when a WebSocket client subscribes, it immediately receives
    in-memory MarketState without waiting for another FiinQuant tick.
    """
    # 1. Populate market_state in memory
    now_ms = int(time.time() * 1000)
    market_state._quotes["HPG"] = CanonicalQuote(
        symbol="HPG",
        instrument_type="STOCK",
        last_price=21850.0,
        reference_price=21800.0,
        bid1_price=21850.0,
        ask1_price=21900.0,
        price_change=50.0,
        price_change_percent=0.0023,
        total_volume=12500000,
        received_timestamp=now_ms,
        source_timestamp=now_ms,
    )

    with patch("app.market_data.market_state.market_session.is_trading_active", return_value=True), \
         patch.object(subscription_manager, "_server_universe_symbols", {"HPG"}):
        with client.websocket_connect("/ws/market") as ws:
            # Status frame
            status_raw = ws.receive_text()
            assert json.loads(status_raw)["type"] == "status"

            # Subscribe to HPG
            ws.send_text(json.dumps({"type": "subscribe", "symbols": ["HPG"]}))

            # Immediate snapshot returned from memory without waiting for live ticks
            snap_raw = ws.receive_text()
            snap_data = json.loads(snap_raw)
            assert snap_data["type"] == "snapshots"
            rows = snap_data["rows"]
            assert len(rows) == 1
            assert rows[0]["Symbol"] == "HPG"
            assert rows[0]["Traded"] == 21.85  # Frontend wire format
            assert rows[0]["Bid1_Prc"] == 21.85
            assert rows[0]["Ask1_Prc"] == 21.90
            assert rows[0]["ChangePercent"] == 0.0023
            assert rows[0]["is_realtime_eligible"] is True


@pytest.mark.asyncio
async def test_backend_restart_warm_cache_restoration_and_overwrite():
    """
    Simulates:
    1. FastAPI process restart (in-memory market_state is empty).
    2. Redis has cached quotes from prior session.
    3. Client connects & subscribes -> quotes restored from Redis and sent in initial snapshot.
    4. Subsequent live FiinQuant tick overwrites the restored quote in memory.
    """
    # Clear in-memory state
    market_state._quotes.clear()

    # Setup Redis store with cached quotes
    now_ms = int(time.time() * 1000)
    mock_redis = MockRedisClient()
    test_store = RedisMarketStateStore(
        enabled=True,
        ttl_seconds=3600,
        max_staleness_seconds=86400,
        redis_client=mock_redis,
    )
    await test_store.initialize()

    cached_hpg = CanonicalQuote(
        symbol="HPG",
        instrument_type="STOCK",
        last_price=21850.0,
        reference_price=21800.0,
        bid1_price=21850.0,
        ask1_price=21900.0,
        total_volume=1000000,
        received_timestamp=now_ms - 5000,
    )
    await test_store.save("HPG", cached_hpg)

    # Patch subscription_manager.store to use test_store and test active session
    with patch("app.market_data.market_websocket.subscription_manager.store", test_store), \
         patch.object(subscription_manager, "_server_universe_symbols", {"HPG"}), \
         patch("app.market_data.market_state.market_session.is_trading_active", return_value=True):
        assert market_state.has_quote("HPG") is False

        with client.websocket_connect("/ws/market") as ws:
            ws.receive_text()  # status
            ws.send_text(json.dumps({"type": "subscribe", "symbols": ["HPG"]}))

            # Verified: Snapshot delivered from warm cache restoration
            snap_raw = ws.receive_text()
            snap_data = json.loads(snap_raw)
            assert snap_data["type"] == "snapshots"
            assert snap_data["rows"][0]["Symbol"] == "HPG"
            assert snap_data["rows"][0]["Traded"] == 21.85

            # MarketState is now warmed in memory
            assert market_state.has_quote("HPG") is True
            hpg_quote = market_state.get_quote("HPG")
            assert hpg_quote is not None
            assert hpg_quote.last_price == 21850.0

    # Now simulate a subsequent live FiinQuant tick arriving with price 21900.0
    new_trade = {
        "Ticker": "HPG",
        "Close": 21900.0,
        "TotalMatchVolume": 1050000,
            "Timestamp": market_session.get_vn_now().replace(hour=10, minute=0, second=0, microsecond=0).isoformat(),
    }
    updated_quote, diff = market_state.apply_trade_event(new_trade)
    assert updated_quote.last_price == 21900.0
    hpg_quote_after = market_state.get_quote("HPG")
    assert hpg_quote_after is not None
    assert hpg_quote_after.last_price == 21900.0

    await test_store.close()


@pytest.mark.asyncio
async def test_reference_metadata_not_sourced_from_redis_cache():
    """
    Asserts that Covered Warrant static reference metadata (issuer, underlying, strike, ratio, maturity)
    remains strictly owned by InstrumentRegistry and is never sourced from Redis market state cache.
    """
    spec = await instrument_registry.get_instrument("CVHM2615")
    assert spec is not None
    assert spec.symbol == "CVHM2615"
    assert spec.underlying_symbol == "VHM"
    assert spec.issuer == "MBS"

    # Even if market cache has null/missing metadata fields, InstrumentRegistry is completely independent
    mock_redis = MockRedisClient()
    store = RedisMarketStateStore(enabled=True, redis_client=mock_redis)
    await store.initialize()
    quote = CanonicalQuote(symbol="CVHM2615", last_price=1810.0)
    await store.save("CVHM2615", quote)

    # Registry remains unaffected
    spec_after = await instrument_registry.get_instrument("CVHM2615")
    assert spec_after is not None
    assert spec_after.underlying_symbol == "VHM"
    assert spec_after.issuer == "MBS"
    await store.close()


def test_market_session_status_and_display_eligibility():
    """
    Tests Vietnam market session windows and display eligibility logic.
    """
    from app.market_data.market_session import MarketSession, MarketSessionStatus, VN_TZ

    ms = MarketSession()

    # 1. Morning Session: Wednesday 10:00 AM VN time
    wed_morning = datetime(2026, 8, 26, 10, 0, 0, tzinfo=VN_TZ)
    assert ms.get_session_status(wed_morning) == MarketSessionStatus.MORNING_SESSION
    assert ms.is_trading_active(wed_morning) is True

    # 2. Lunch Break: Wednesday 12:00 PM VN time
    wed_lunch = datetime(2026, 8, 26, 12, 0, 0, tzinfo=VN_TZ)
    assert ms.get_session_status(wed_lunch) == MarketSessionStatus.LUNCH_BREAK
    assert ms.is_trading_active(wed_lunch) is False

    # 3. Afternoon Session: Wednesday 14:00 PM VN time
    wed_afternoon = datetime(2026, 8, 26, 14, 0, 0, tzinfo=VN_TZ)
    assert ms.get_session_status(wed_afternoon) == MarketSessionStatus.AFTERNOON_SESSION
    assert ms.is_trading_active(wed_afternoon) is True

    # 4. Post Market: Wednesday 16:00 PM VN time
    wed_post = datetime(2026, 8, 26, 16, 0, 0, tzinfo=VN_TZ)
    assert ms.get_session_status(wed_post) == MarketSessionStatus.CLOSED_POST_MARKET
    assert ms.is_trading_active(wed_post) is False

    # 5. Weekend: Sunday 10:00 AM VN time
    sun_morning = datetime(2026, 8, 30, 10, 0, 0, tzinfo=VN_TZ)
    assert ms.get_session_status(sun_morning) == MarketSessionStatus.CLOSED_WEEKEND
    assert ms.is_trading_active(sun_morning) is False

    # 6. Display Eligibility:
    # During lunch break, a quote is NOT realtime display eligible
    now_ms = int(wed_lunch.timestamp() * 1000)
    assert ms.is_display_eligible(now_ms, dt=wed_lunch) is False

    # During active morning session, fresh quote IS eligible
    morning_now_ms = int(wed_morning.timestamp() * 1000)
    assert ms.is_display_eligible(morning_now_ms, dt=wed_morning) is True


def test_quote_wire_snapshot_row_display_eligibility():
    """
    Tests that when display_eligible is False (e.g. during lunch break),
    realtime trade/depth fields are stripped to None, but static reference terms remain.
    """
    quote = CanonicalQuote(
        symbol="CVHM2615",
        instrument_type="CW",
        underlying_symbol="VHM",
        strike_price=45000.0,
        exercise_ratio=5.0,
        last_price=1810.0,
        reference_price=1800.0,
        bid1_price=1810.0,
        bid1_quantity=5000,
        ask1_price=1840.0,
        ask1_quantity=8000,
        price_change=10.0,
        price_change_percent=0.0055,
        total_volume=50000,
    )

    # When eligible (active session):
    row_active = quote.to_wire_snapshot_row(display_eligible=True)
    assert row_active["Traded"] == 1.81
    assert row_active["Bid1_Prc"] == 1.81
    assert row_active["Ask1_Prc"] == 1.84
    assert row_active["ChangePercent"] == 0.0055
    assert row_active["Total_Vol"] == 50000
    assert row_active["Strike_Prc"] == 45.0
    assert row_active["is_realtime_eligible"] is True

    # When ineligible (lunch break / closed):
    row_lunch = quote.to_wire_snapshot_row(display_eligible=False)
    assert row_lunch["Traded"] is None
    assert row_lunch["Bid1_Prc"] is None
    assert row_lunch["Ask1_Prc"] is None
    assert row_lunch["ChangePercent"] is None
    assert row_lunch["Total_Vol"] is None
    assert row_lunch["Strike_Prc"] == 45.0  # Static reference data preserved
    assert row_lunch["Under_Symbol"] == "VHM"
    assert row_lunch["Ratio"] == 5.0
    assert row_lunch["is_realtime_eligible"] is False


def test_subscription_manager_exact_replacement_semantics():
    """
    Tests that set_exact_subscriptions strictly replaces active subscriptions
    and does not accumulate unwanted old symbols (like CVHM2601).
    """
    mock_prov = MockMarketDataProvider(max_symbols=10)
    mgr = SubscriptionManager(provider=mock_prov, max_symbols=10, debounce_ms=10)

    # 1. Initial subscription with an old symbol
    mgr.set_exact_subscriptions(["CVHM2601", "HPG", "VHM"])
    assert set(mgr.get_desired_symbols()) == {"CVHM2601", "HPG", "VHM"}

    # 2. Frontend replaces with canonical 5-symbol universe
    canonical_five = ["HPG", "NVL", "VHM", "CVHM2615", "CHPG2541"]
    mgr.set_exact_subscriptions(canonical_five)

    # 3. Verify CVHM2601 is completely gone
    desired = mgr.get_desired_symbols()
    assert len(desired) == 5
    assert "CVHM2601" not in desired
    assert set(desired) == set(canonical_five)


def test_sensitive_data_logging_redaction():
    """
    Tests that SensitiveDataRedactor masks Bearer authorization tokens and passwords.
    """
    import logging
    from app.main import SensitiveDataRedactor

    redactor = SensitiveDataRedactor()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="Connecting with headers: {'Authorization': 'Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.dummy_token_payload'}",
        args=(),
        exc_info=None,
    )
    redactor.filter(record)
    assert "Bearer [REDACTED]" in record.msg
    assert "eyJ" not in record.msg


@pytest.mark.asyncio
async def test_real_local_redis_integration():
    """
    Integration test connecting to actual local Redis daemon on 127.0.0.1:6379.
    Validates end-to-end save, key naming, process restart simulation, and hydration.
    """
    import redis.asyncio as aioredis
    try:
        test_client = aioredis.from_url("redis://127.0.0.1:6379/0", decode_responses=True)
        await test_client.ping()
    except Exception:
        pytest.skip("Local Redis server not running on 127.0.0.1:6379")

    real_store = RedisMarketStateStore(
        enabled=True,
        redis_url="redis://127.0.0.1:6379/0",
        ttl_seconds=300,
        max_staleness_seconds=86400,
    )
    await real_store.initialize()
    assert real_store.is_available() is True

    # 1. Save canonical quote for HPG
    now_ms = int(time.time() * 1000)
    hpg_quote = CanonicalQuote(
        symbol="HPG",
        instrument_type="STOCK",
        last_price=21850.0,
        reference_price=21800.0,
        bid1_price=21850.0,
        ask1_price=21900.0,
        total_volume=12500000,
        received_timestamp=now_ms,
        source_timestamp=now_ms,
    )
    await real_store.save("HPG", hpg_quote)

    # 2. Verify Redis key exists directly in Redis
    raw_key = "cw_research:market_state:v1:HPG"
    exists = await test_client.exists(raw_key)
    assert exists == 1

    # 3. Simulate process restart: create fresh MarketState instance (empty L1)
    fresh_market_state = MarketState()
    assert fresh_market_state.has_quote("HPG") is False

    # 4. Hydrate from real Redis
    restored_quotes = await real_store.load_many(["HPG", "CVHM2615"])
    assert "HPG" in restored_quotes
    fresh_market_state.restore_quotes(restored_quotes)

    # 5. Verify L1 state restored accurately in canonical units
    assert fresh_market_state.has_quote("HPG") is True
    restored_hpg = fresh_market_state.get_quote("HPG")
    assert restored_hpg is not None
    assert restored_hpg.last_price == 21850.0
    assert restored_hpg.received_timestamp == now_ms

    # Cleanup
    await test_client.delete(raw_key)
    await real_store.close()
    await test_client.aclose()
