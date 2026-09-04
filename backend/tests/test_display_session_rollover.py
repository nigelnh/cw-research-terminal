"""The display day begins at 08:00 ICT; it is independent of the first match."""
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.market_data.market_schemas import CanonicalQuote
from app.market_data.market_state import MarketState, market_state
from app.market_data.market_snapshot_resolver import MarketSnapshotResolver
from app.market_data.market_subscription_manager import SubscriptionManager
from app.market_data.session_reference import reference_session_date


def at(day, clock):
    return datetime.fromisoformat(f"2026-09-{day:02d}T{clock}:00+07:00")


@pytest.mark.parametrize("day,clock,expected", [
    (3, "15:00", "2026-09-03"), (3, "23:59", "2026-09-03"),
    (4, "00:00", "2026-09-03"), (4, "07:59", "2026-09-03"),
    (4, "08:00", "2026-09-04"), (4, "09:00", "2026-09-04"),
    (4, "11:30", "2026-09-04"), (4, "13:00", "2026-09-04"),
    (4, "14:30", "2026-09-04"), (4, "15:00", "2026-09-04"),
    (5, "08:00", "2026-09-04"), (6, "09:00", "2026-09-04"),
    (7, "07:59", "2026-09-04"), (7, "08:00", "2026-09-07"),
    (2, "08:00", "2026-08-28"),
])
def test_reference_display_day(day, clock, expected):
    assert reference_session_date(at(day, clock)).isoformat() == expected


def closing_quote():
    ts = int(at(3, "14:45").timestamp() * 1000)
    return CanonicalQuote(symbol="HPG", instrument_type="STOCK", last_price=21600,
        total_volume=27036617, traded_quantity=100, bid1_price=21600, ask1_price=21650,
        reference_price=22000, ceiling_price=23500, floor_price=20500,
        market_session_date="2026-09-03", reference_session_date="2026-09-03",
        trade_timestamp=ts, book_timestamp=ts, source_timestamp=ts, received_timestamp=ts)


def test_clock_clears_and_publishes_new_session_without_any_provider_event(monkeypatch):
    from app.market_data.market_session import market_session
    state = MarketState()
    state.restore_quote(closing_quote())
    mgr = SubscriptionManager(provider=Mock(), state=state, store=Mock())
    mgr._schedule_reference_refresh = Mock()
    patch, status = Mock(), Mock()
    mgr.register_patch_listener(patch)
    mgr.register_status_listener(status)
    monkeypatch.setattr(market_session, "get_vn_now", lambda: at(4, "07:59"))
    mgr._session_clock_tick()
    assert state.get_quote("HPG").last_price == 21600
    patch.assert_not_called()
    monkeypatch.setattr(market_session, "get_vn_now", lambda: at(4, "08:00"))
    mgr._session_clock_tick()
    q = state.get_quote("HPG")
    assert q.last_price is q.total_volume is q.traded_quantity is q.reference_price is None
    assert q.trade_timestamp is q.book_timestamp is None
    assert q.market_session_date == "2026-09-04"
    assert patch.call_args.args[0]["patch"]["Traded"] is None
    mgr._schedule_reference_refresh.assert_called_with("2026-09-04")
    mgr._session_clock_tick()
    assert patch.call_count == 1
    mgr.provider.set_subscriptions.assert_not_called()
    assert status.call_count == 2
    _, diff = state.apply_trade_event({"Ticker": "HPG", "Timestamp": "2026-09-03T14:46:00+07:00", "Close": 22000})
    assert not diff


@pytest.mark.asyncio
async def test_resolver_holds_overnight_then_waits_for_real_new_session_trade(monkeypatch):
    monkeypatch.setattr(market_state, "_quotes", {})
    resolver = MarketSnapshotResolver()
    closing = closing_quote()
    market_state.restore_quote(closing)
    resolver._load_snapshots = AsyncMock(return_value={})
    resolver._recent_daily_bars = AsyncMock(side_effect=AssertionError("must not seed new-session trades"))
    overnight = (await resolver.resolve_rows(["HPG"], now=at(4, "07:59")))[0]
    assert overnight.values["last_price"] == 21600
    assert overnight.quote_prov.state.value == "LAST_SESSION"
    market_state.apply_reference_metadata("HPG", session_date="2026-09-04", reference_price=21600,
        ceiling_price=23100, floor_price=20100)
    pending = (await resolver.resolve_rows(["HPG"], now=at(4, "08:00")))[0]
    assert pending.values.get("last_price") is None
    assert pending.values["reference_price"] == 21600
    assert pending.quote_prov.state.value == "UNAVAILABLE"
    market_state.apply_bidask_event({"Ticker": "HPG", "Timestamp": "2026-09-04T09:00:00+07:00",
        "Best1Bid": 21650, "Best1Ask": 21700})
    ato = (await resolver.resolve_rows(["HPG"], now=at(4, "09:00")))[0]
    assert ato.values.get("last_price") is None
    assert ato.values["bid1_price"] == 21650


@pytest.mark.asyncio
async def test_redis_restore_before_8_keeps_closing_trade_and_bands(monkeypatch):
    from app.market_data.market_session import market_session
    import app.market_data.market_subscription_manager as module
    monkeypatch.setattr(market_session, "get_vn_now", lambda: at(4, "07:59"))
    monkeypatch.setattr(module, "reference_session_date", lambda now=None: date(2026, 9, 3))
    state = MarketState()
    store = Mock()
    store.load_many = AsyncMock(return_value={"HPG": closing_quote()})
    manager = SubscriptionManager(provider=Mock(), state=state, store=store)
    await manager.hydrate_missing_market_state(["HPG"])
    restored = state.get_quote("HPG")
    assert (restored.last_price, restored.total_volume, restored.traded_quantity) == (21600, 27036617, 100)
    assert restored.ceiling_price == 23500


@pytest.mark.asyncio
async def test_prior_final_snapshot_cannot_seed_new_session_after_8(monkeypatch):
    monkeypatch.setattr(market_state, "_quotes", {})
    resolver = MarketSnapshotResolver()
    resolver._load_snapshots = AsyncMock(return_value={"HPG": SimpleNamespace(session_date=date(2026, 9, 3))})
    row = (await resolver.resolve_rows(["HPG"], now=at(4, "10:00"), enrich_snapshot_history=False))[0]
    assert row.values.get("last_price") is None
    assert row.quote_prov.session_date == "2026-09-04"
