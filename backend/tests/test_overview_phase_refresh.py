"""The overview is rebuilt when the market phase changes, not up to two minutes later.

At 09:16 on 2026-10-12 the index cards still showed the payload built during ATO - no
matched value, no leaders - because the service kept it for its 60 s TTL and the provider
kept its own copy for another 60 s. It filled in by about 09:2x.
"""

from __future__ import annotations

import time
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.market_data.market_overview_service import MarketOverviewService, market_overview_service
from app.market_data.market_session import market_session
from app.market_data.market_state import MarketState
from app.market_data.market_subscription_manager import SubscriptionManager, subscription_manager
from app.market_data.providers.vnstock_provider import VnstockProvider
from app.market_data.trading_calendar import VN_TZ, MarketPhase


@pytest.fixture(autouse=True)
def fixed_session(monkeypatch):
    monkeypatch.setattr(
        "app.market_data.market_overview_service.reference_session_date", lambda *a: date(2026, 9, 3)
    )


class Phase:
    """The market phase, as the tests set it."""

    def __init__(self, monkeypatch, phase: MarketPhase):
        self.now = phase
        monkeypatch.setattr(market_session, "get_market_phase", lambda *a: self.now)
        monkeypatch.setattr(market_session, "is_trading_active", lambda *a: True)


def overview():
    index = {"symbol": "VNINDEX", "value": 1200, "as_of": "2026-09-03", "session_date": "2026-09-03",
             "provenance": {"price": {"session_date": "2026-09-03"}}}
    return {"indices": [index], "top_stock_volume": [], "top_cw_volume": [],
            "availability": "AVAILABLE", "components": {"top_stock_volume": "AVAILABLE"}}


def service_with(saved=None):
    provider = SimpleNamespace(get_market_overview=AsyncMock(side_effect=lambda *a, **k: overview()))
    store = SimpleNamespace(load_market_overview=AsyncMock(return_value=saved),
                            save_market_overview=AsyncMock())
    service = MarketOverviewService()
    service.configure(provider, store)
    return service, provider, store


async def settle(service: MarketOverviewService) -> None:
    if service._refresh_task is not None:
        await service._refresh_task


# ---------------------------------------------------------------------------- service #

@pytest.mark.asyncio
async def test_a_payload_built_during_ato_is_rebuilt_on_the_first_read_after_it(monkeypatch):
    phase = Phase(monkeypatch, MarketPhase.ATO)
    service, provider, store = service_with()
    try:
        await service.get([])
        await settle(service)
        await service.get([])  # same phase, seconds old: the cache answers
        await settle(service)
        assert provider.get_market_overview.await_count == 1
        assert store.save_market_overview.await_args.args[0]["phase"] == "ATO"

        phase.now = MarketPhase.CONTINUOUS_AM
        await service.get([])
        await settle(service)
        assert provider.get_market_overview.await_count == 2
        assert service._cached_phase == "CONTINUOUS_AM"
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_for_a_minute_after_a_phase_change_the_session_ttl_is_short(monkeypatch):
    phase = Phase(monkeypatch, MarketPhase.ATO)
    service, _, _ = service_with()
    service._current_phase()
    assert service._ttl_seconds() == 60.0

    phase.now = MarketPhase.CONTINUOUS_AM
    service._current_phase()
    # The first refresh may land before the auction result is published: ask again soon.
    assert service._ttl_seconds() == service._SETTLING_TTL_SECONDS == 15.0
    service._phase_changed_at -= service._PHASE_SETTLE_SECONDS + 1
    assert service._ttl_seconds() == 60.0


@pytest.mark.asyncio
async def test_a_restored_payload_remembers_its_phase(monkeypatch):
    Phase(monkeypatch, MarketPhase.CONTINUOUS_AM)
    built_in_ato = {"payload": overview(), "cached_at": time.time(), "phase": "ATO"}
    service, provider, _ = service_with(built_in_ato)
    try:
        await service.get([])
        await settle(service)
        assert provider.get_market_overview.await_count == 1
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_a_restored_payload_of_unknown_phase_is_judged_by_age_alone(monkeypatch):
    Phase(monkeypatch, MarketPhase.CONTINUOUS_AM)
    legacy = {"payload": overview(), "cached_at": time.time()}
    service, provider, _ = service_with(legacy)
    try:
        await service.get([])
        await settle(service)
        assert provider.get_market_overview.await_count == 0
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_a_phase_change_refreshes_without_waiting_for_a_read(monkeypatch):
    phase = Phase(monkeypatch, MarketPhase.ATO)
    service, provider, _ = service_with()
    service.start_refresh(["CHPG2625"])
    await settle(service)
    assert provider.get_market_overview.await_count == 1

    phase.now = MarketPhase.CONTINUOUS_AM
    service.on_market_phase_change()
    await settle(service)
    assert provider.get_market_overview.await_count == 2
    assert provider.get_market_overview.await_args.args[0] == ["CHPG2625"]
    assert service._ttl_seconds() == 15.0
    await service.close()


# --------------------------------------------------------------------------- provider #

class Fetched(Exception):
    """Raised by the first upstream read: proof the provider did not answer from cache."""


def provider_with_cache(phase: str, age: float) -> VnstockProvider:
    p = VnstockProvider()

    async def fetch(*_a, **_k):
        raise Fetched

    p._safe_group_symbols = fetch
    cached = {"cached": True}
    p._overview_cache = (time.monotonic() - age, cached)
    p._overview_cache_phase = phase
    return p


@pytest.mark.asyncio
async def test_the_provider_answers_from_cache_only_within_one_phase(monkeypatch):
    phase = Phase(monkeypatch, MarketPhase.CONTINUOUS_AM)
    assert await provider_with_cache("CONTINUOUS_AM", age=1).get_market_overview([]) == {"cached": True}
    with pytest.raises(Fetched):
        await provider_with_cache("ATO", age=1).get_market_overview([])
    phase.now = MarketPhase.ATO
    assert await provider_with_cache("ATO", age=1).get_market_overview([]) == {"cached": True}


@pytest.mark.asyncio
async def test_the_providers_copy_never_outlives_the_services_short_ttl(monkeypatch):
    Phase(monkeypatch, MarketPhase.CONTINUOUS_AM)
    assert VnstockProvider._OVERVIEW_TTL < MarketOverviewService._SETTLING_TTL_SECONDS
    with pytest.raises(Fetched):
        await provider_with_cache(
            "CONTINUOUS_AM", age=MarketOverviewService._SETTLING_TTL_SECONDS
        ).get_market_overview([])


# ------------------------------------------------------------------------ session clock #

def at(clock: str) -> datetime:
    return datetime.fromisoformat(f"2026-09-04T{clock}+07:00")  # a Friday


def test_phase_listeners_hear_each_change_once_and_not_the_first_tick(monkeypatch):
    mgr = SubscriptionManager(provider=Mock(), state=MarketState(), store=Mock())
    mgr._schedule_reference_refresh = Mock()
    heard = Mock()
    mgr.register_phase_listener(heard)

    for clock, calls in (("09:14:58", 0), ("09:14:59", 0), ("09:15:00", 1), ("09:15:01", 1),
                         ("12:59:59", 2), ("13:00:00", 3)):
        monkeypatch.setattr(market_session, "get_vn_now", lambda clock=clock: at(clock))
        mgr._session_clock_tick()
        assert heard.call_count == calls, clock


def test_a_failing_phase_listener_does_not_stop_the_clock(monkeypatch):
    mgr = SubscriptionManager(provider=Mock(), state=MarketState(), store=Mock())
    mgr._schedule_reference_refresh = Mock()
    heard = Mock()
    mgr.register_phase_listener(Mock(side_effect=RuntimeError("boom")))
    mgr.register_phase_listener(heard)
    for clock in ("09:14:59", "09:15:00"):
        monkeypatch.setattr(market_session, "get_vn_now", lambda clock=clock: at(clock))
        mgr._session_clock_tick()
    assert heard.call_count == 1


# ------------------------------------------------------------------------------ wiring #

def test_startup_tells_the_overview_about_phase_changes():
    with TestClient(app):
        assert market_overview_service.on_market_phase_change in subscription_manager._phase_listeners
