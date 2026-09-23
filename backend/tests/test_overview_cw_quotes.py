"""Live covered-warrant values the overview ranks by, and the two it must refuse.

The KBS price board reports volume_accumulated and close_price as literal 0 for every
covered warrant while giving stocks real numbers, so the provider's zero-volume guard
dropped all of them and TOP COVERED WARRANTS TRADING VOLUME read DATA UNAVAILABLE for a
whole session. The figures were never missing - the watchlist had 740,700 for CACB2606 at
the same moment the board said 0 - they arrive on the realtime feed instead.
"""
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.market_data.market_overview_service import (
    MarketOverviewService,
    _live_cw_quotes,
)

SESSION = "2026-09-23"


class _Quote:
    def __init__(self, **kw):
        self.total_volume = kw.get("total_volume")
        self.last_price = kw.get("last_price")
        self.reference_price = kw.get("reference_price")
        self.ceiling_price = kw.get("ceiling_price")
        self.floor_price = kw.get("floor_price")
        self.trade_timestamp = kw.get("trade_timestamp")
        self.source_timestamp = kw.get("source_timestamp")
        self.market_session_date = kw.get("market_session_date", SESSION)


def _with(quotes):
    return patch(
        "app.market_data.market_overview_service.market_state.get_quote",
        side_effect=lambda s: quotes.get(s),
    )


def test_it_carries_the_values_the_ranking_needs():
    quotes = {"CACB2606": _Quote(
        total_volume=740_700, last_price=610, reference_price=600,
        ceiling_price=1000, floor_price=10, trade_timestamp="2026-09-23T10:00:00+07:00",
    )}
    with _with(quotes):
        out = _live_cw_quotes(["CACB2606"], SESSION)
    assert out["CACB2606"] == {
        "total_volume": 740_700, "last_price": 610, "reference_price": 600,
        "ceiling_price": 1000, "floor_price": 10, "as_of": "2026-09-23T10:00:00+07:00",
    }


def test_a_warrant_that_has_not_traded_is_left_out():
    """Zero volume is a placeholder either way - the source it came from does not change
    that, and ranking it would rebuild the fabricated table this guard exists to prevent."""
    quotes = {"A": _Quote(total_volume=0, last_price=100), "B": _Quote(total_volume=None)}
    with _with(quotes):
        assert _live_cw_quotes(["A", "B"], SESSION) == {}


def test_a_quote_stamped_for_another_session_is_refused():
    """Yesterday's volume presented as today's is exactly the failure this table already
    guards against elsewhere."""
    quotes = {"OLD": _Quote(total_volume=999, market_session_date="2026-09-22")}
    with _with(quotes):
        assert _live_cw_quotes(["OLD"], SESSION) == {}


def test_a_quote_with_no_session_stamp_is_still_usable():
    """An unstamped quote is not evidence of the WRONG session; refusing it would empty the
    table on any feed that does not carry the field."""
    quotes = {"X": _Quote(total_volume=12_345, last_price=500, market_session_date=None)}
    with _with(quotes):
        assert _live_cw_quotes(["X"], SESSION)["X"]["total_volume"] == 12_345


def test_a_symbol_with_no_quote_at_all_is_skipped():
    with _with({}):
        assert _live_cw_quotes(["NOPE"], SESSION) == {}


def test_it_falls_back_to_the_source_stamp_when_no_trade_stamp_exists():
    quotes = {"Y": _Quote(total_volume=5, source_timestamp="2026-09-23T09:15:00+07:00")}
    with _with(quotes):
        assert _live_cw_quotes(["Y"], SESSION)["Y"]["as_of"] == "2026-09-23T09:15:00+07:00"


# --------------------------------------------------------------------------- #
# The join. Both halves above can be right while nothing reaches the provider:
# the map is built in the service and read in the provider, and only the refresh
# loop puts the two together.
# --------------------------------------------------------------------------- #
def _payload():
    return {
        "indices": [], "top_stock_volume": [], "top_cw_volume": [{"symbol": "CACB2606"}],
        "source": "VNSTOCK", "availability": "AVAILABLE", "as_of": SESSION,
        "components": {"top_stock_volume": "AVAILABLE"},
    }


@pytest.mark.asyncio
async def test_the_refresh_hands_live_warrant_values_to_the_provider(monkeypatch):
    monkeypatch.setattr(
        "app.market_data.market_overview_service.reference_session_date",
        lambda *a: date(2026, 9, 23),
    )
    provider = SimpleNamespace(get_market_overview=AsyncMock(return_value=_payload()))
    service = MarketOverviewService()
    service.configure(provider, SimpleNamespace(
        load_market_overview=AsyncMock(return_value=None),
        save_market_overview=AsyncMock(),
    ))
    quotes = {"CACB2606": _Quote(total_volume=740_700, last_price=1.23)}
    try:
        with _with(quotes):
            service.start_refresh(["CACB2606"])
            await service._refresh_task
    finally:
        await service.close()

    kwargs = provider.get_market_overview.await_args.kwargs
    assert kwargs["cw_quotes"]["CACB2606"]["total_volume"] == 740_700, (
        "the provider must receive the live map, or the board's zero rows win again"
    )
