from __future__ import annotations

import os
import time
from datetime import date, datetime

import pytest

from app.market_data.market_schemas import CanonicalQuote
from app.market_data.providers.vnstock_provider import VnstockProvider
from app.market_data.traded_log import TradedLog
from app.market_data.trading_calendar import VN_TZ

SESSION = "2026-09-08"
STAMP_MS = int(datetime(2026, 9, 8, 10, 54, 59, tzinfo=VN_TZ).timestamp() * 1000)


def board_row(symbol="CHPG2625", session="08/09/2026"):
    return {
        "symbol": symbol, "TD": session, "time": STAMP_MS,
        "close_price": 590, "reference_price": 550, "ceiling_price": 1300,
        "floor_price": 10, "open_price": 560, "high_price": 600,
        "low_price": 560, "average_price": 575, "price_change": 40,
        "percent_change": 7.272727, "volume_accumulated": 541300,
        "total_value": 311694000, "bid_price_1": "570.0", "bid_vol_1": 10000,
        "ask_price_1": "580.0", "ask_vol_1": 100000,
    }


def provider(**kwargs):
    p = VnstockProvider(**kwargs)
    p._request_floor = 0
    return p


@pytest.mark.asyncio
async def test_board_is_emitted_in_raw_vnd_with_confirmed_session():
    p = provider(board_fetcher=lambda symbols: [board_row()])
    events = []
    p.set_event_callback(lambda kind, row, symbol: events.append((kind, row, symbol)))
    p._active_symbols = ["CHPG2625"]

    assert await p._poll_quotes_once() == 2
    trade = next(row for kind, row, _ in events if kind == "trade")
    book = next(row for kind, row, _ in events if kind == "bidask")
    assert trade["Close"] == 590
    assert trade["Reference"] == 550
    assert trade["PercentPriceChange"] == pytest.approx(0.07272727)
    assert trade["TradingDate"] == SESSION
    assert trade["_synthetic_session_snapshot"] is True
    assert book["Best1Bid"] == 570
    assert book["Best1Ask"] == 580
    assert trade["Timestamp"].startswith(f"{SESSION}T10:54:59")


@pytest.mark.asyncio
async def test_reference_and_snapshot_reject_a_different_session(monkeypatch):
    p = provider(board_fetcher=lambda symbols: [board_row(session="07/09/2026")])
    assert await p.get_session_reference_data(["CHPG2625"], date(2026, 9, 8)) == {}
    assert await p.get_session_trade_snapshot(["CHPG2625"], date(2026, 9, 8)) == {}


@pytest.mark.asyncio
async def test_reference_keeps_independent_provider_fields():
    row = board_row()
    row["ceiling_price"] = None
    p = provider(board_fetcher=lambda symbols: [row])
    result = await p.get_session_reference_data(["CHPG2625"], date(2026, 9, 8))
    assert result["CHPG2625"]["reference_price"] == 550
    assert result["CHPG2625"]["ceiling_price"] is None
    assert result["CHPG2625"]["floor_price"] == 10
    assert result["CHPG2625"]["session_date"] == SESSION
    assert result["CHPG2625"]["source"] == "VNSTOCK_KBS_PRICE_BOARD"


@pytest.mark.asyncio
async def test_reference_and_session_snapshot_share_recent_board_observation():
    calls = []

    def fetch(symbols):
        calls.append(symbols)
        return [board_row()]

    p = provider(board_fetcher=fetch)
    first = await p.get_session_reference_data(["CHPG2625"], date(2026, 9, 8))
    second = await p.get_session_trade_snapshot(["CHPG2625"], date(2026, 9, 8))
    assert first["CHPG2625"]["reference_price"] == 550
    assert second["CHPG2625"]["last_price"] == 590
    assert second["CHPG2625"]["session_date"] == SESSION
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_kbs_history_is_rescaled_to_raw_vnd(monkeypatch):
    def fetch(symbol, source, start, end, interval):
        assert source == "kbs"
        return [{"time": "2026-09-07 07:00:00", "open": .56, "high": .61,
                 "low": .55, "close": .55, "volume": 541100}]

    p = provider(history_fetcher=fetch)
    bars = await p.get_historical_bars(
        "CHPG2625", from_date="2026-09-07", to_date="2026-09-07", adjusted=True
    )
    assert [(b.open, b.high, b.low, b.close) for b in bars] == [(560, 610, 550, 550)]
    assert bars[0].adjusted is False
    assert bars[0].price_basis == "RAW"
    assert bars[0].source == "VNSTOCK_KBS"


@pytest.mark.asyncio
async def test_vci_equity_history_is_rescaled_and_marked_adjusted():
    def fetch(symbol, source, start, end, interval):
        assert source == "vci"
        return [{"time": "2026-09-07 07:00:00", "open": 21.8, "high": 22.15,
                 "low": 21.55, "close": 21.55, "volume": 19957800}]

    p = provider(history_fetcher=fetch)
    bars = await p.get_historical_bars(
        "HPG", from_date="2026-09-07", to_date="2026-09-07", adjusted=True
    )
    assert bars[0].close == 21550
    assert bars[0].adjusted is True
    assert bars[0].price_basis == "ADJUSTED"
    assert bars[0].source == "VNSTOCK_VCI"


@pytest.mark.asyncio
async def test_history_filters_vendor_warmup_rows_outside_requested_range():
    p = provider(history_fetcher=lambda *args: [
        {"time": "2026-09-04 07:00:00", "open": 21, "high": 22,
         "low": 20, "close": 21, "volume": 1},
        {"time": "2026-09-08 07:00:00", "open": 22, "high": 23,
         "low": 21, "close": 22, "volume": 2},
    ])
    bars = await p.get_historical_bars(
        "HPG", from_date="2026-09-07", to_date="2026-09-08", adjusted=True
    )
    assert [bar.session_date for bar in bars] == ["2026-09-08"]


def test_tape_normalization_uses_full_footprint_for_dedup(monkeypatch):
    p = provider()
    events = []
    p.set_event_callback(lambda kind, row, symbol: events.append((kind, row, symbol)))
    rows = [
        {"time": "2026-09-08 10:54:59", "price": .59, "volume": 1000,
         "match_type": "buy", "id": "same", "trading_date": "08/09/2026",
         "accumulated_volume": 484400, "accumulated_value": 278123000},
        {"time": "2026-09-08 10:54:59", "price": .59, "volume": 1000,
         "match_type": "buy", "id": "same", "trading_date": "08/09/2026",
         "accumulated_volume": 485400, "accumulated_value": 278713000},
    ]
    monkeypatch.setattr(
        "app.market_data.providers.vnstock_provider.reference_session_date",
        lambda *args, **kwargs: date(2026, 9, 8),
    )
    p._emit_confirmed_prints("CHPG2625", rows)
    p._emit_confirmed_prints("CHPG2625", rows)
    prints = [row for kind, row, _ in events if kind == "trade_print"]
    assert len(prints) == 2
    assert prints[0]["Close"] == 590
    assert prints[0]["MatchVolume"] == 1000
    assert prints[0]["TradeId"] != prints[1]["TradeId"]


def test_confirmed_provider_print_does_not_require_quote_rollback(monkeypatch):
    monkeypatch.setattr(
        "app.market_data.traded_log.reference_session_date", lambda *args, **kwargs: date(2026, 9, 8)
    )
    tape = TradedLog(max_entries=10, memory_entries=10)
    quote = CanonicalQuote(
        symbol="CHPG2625", instrument_type="CW", last_price=600, reference_price=550,
        bid1_price=590, ask1_price=600, market_session_date=SESSION,
    )
    raw = {
        "Timestamp": "2026-09-08T10:54:59+07:00", "TradingDate": SESSION,
        "Close": 590, "MatchVolume": 1000, "TotalMatchVolume": 484400,
        "Side": "buy", "TradeId": "confirmed-1",
    }
    item = tape.record_provider_print("CHPG2625", raw, quote=quote)
    assert item["price"] == 590
    assert item["side"] == "B"
    assert item["side_basis"] == "PROVIDER"
    assert quote.last_price == 600
    assert tape.get("CHPG2625")["side_basis"] == "PROVIDER"


@pytest.mark.asyncio
async def test_profiles_normalize_hsx_to_hose():
    p = provider(listing_fetcher=lambda: [{
        "symbol": "HPG", "exchange": "HSX", "type": "STOCK",
        "organ_name": "Hoa Phat", "organ_short_name": "HPG",
    }])
    rows = await p.get_stock_profiles(["HPG"])
    assert rows == [{"symbol": "HPG", "name": "Hoa Phat", "short_name": "HPG",
                     "exchange": "HOSE", "source": "VNSTOCK_VCI"}]


@pytest.mark.asyncio
async def test_fundamentals_use_latest_quarter_and_expose_available_ratios():
    p = provider(fundamentals_fetcher=lambda symbol: [
        {"year": "2026", "quarter": 1, "pe": 8, "pb": 1.2},
        {"year": "2026", "quarter": 2, "pe": 7.9, "pb": 1.3,
         "after_tax_profit_margin": .115, "roe": .21, "roa": .12,
         "roic": .18, "gross_margin": .24, "ebit": 12_000},
    ])
    valuation = await p.get_stock_valuation(["HPG"])
    ratios = await p.get_financial_ratios("HPG")
    assert valuation["HPG"] == {"symbol": "HPG", "pe": 7.9, "pb": 1.3, "as_of": "2026Q2"}
    assert ratios[-1]["period"] == "2026Q2"
    assert ratios[-1]["net_margin"] == .115
    assert ratios[-1]["roe"] == .21


def test_health_does_not_report_previous_session_data_as_fresh(monkeypatch):
    p = provider()
    p._connected = True
    p._active_symbols = ["HPG"]
    p._quote_task = type("Task", (), {"done": lambda self: False})()
    p._last_board_check_monotonic = time.monotonic()
    p._last_data_session = "2026-09-07"
    p._last_data_at_ms = int(datetime(2026, 9, 7, 15, 0, tzinfo=VN_TZ).timestamp() * 1000)
    monkeypatch.setattr(
        "app.market_data.providers.vnstock_provider.reference_session_date",
        lambda *args, **kwargs: date(2026, 9, 8),
    )
    monkeypatch.setattr(
        "app.market_data.providers.vnstock_provider.market_session.is_trading_active",
        lambda: True,
    )

    health = p.get_health()
    assert health["feed_fresh"] is False
    assert health["upstream_status"] == "CONNECTING"
    assert health["feedStatus"]["code"] == "AWAITING_DATA"
    assert health["feedStatus"]["lastDataAt"] is None
    assert health["last_tick_at"] is not None


@pytest.mark.asyncio
async def test_overview_keeps_other_indices_when_one_dataset_fails(monkeypatch):
    def history(symbol, source, start, end, interval):
        if symbol == "VNFINLEAD":
            raise RuntimeError("connection error")
        if interval == "1D":
            return [
                {"time": "2026-09-07 15:00:00", "close": 1000, "volume": 1},
                {"time": "2026-09-08 15:00:00", "close": 1010, "volume": 2},
            ]
        return [{"time": "2026-09-08 09:05:00", "close": 1005, "volume": 1}]

    def board(symbols):
        return [
            {**board_row(symbol=symbol), "close_price": 22000, "reference_price": 21500}
            for symbol in symbols
        ]

    def group(name):
        if name == "VNFINLEAD":
            raise RuntimeError("connection error")
        return ["HPG"]

    p = provider(
        board_fetcher=board,
        history_fetcher=history,
        listing_fetcher=lambda: [{"symbol": "HPG", "exchange": "HSX", "type": "STOCK"}],
        group_fetcher=group,
    )
    monkeypatch.setattr(
        "app.market_data.providers.vnstock_provider.reference_session_date",
        lambda *args, **kwargs: date(2026, 9, 8),
    )
    result = await p.get_market_overview(["CHPG2625"])
    by_symbol = {item["symbol"]: item for item in result["indices"]}
    assert by_symbol["VNINDEX"]["value"] == 1010
    assert by_symbol["VNFINLEAD"]["availability"] == "UNAVAILABLE"
    assert "PRICE_UNAVAILABLE" in by_symbol["VNFINLEAD"]["partial_reasons"]
    assert by_symbol["VNDIAMOND"]["breadth_expected"] == 1
    assert by_symbol["VNDIAMOND"]["breadth_observed"] == 1
    assert result["availability"] == "PARTIAL"
    assert result["top_stock_volume"]


def test_adapter_disables_vendor_agent_file_injection():
    assert os.environ["VNSTOCK_DISABLE_AGENT_SETUP"] == "1"
    assert os.environ["VNSTOCK_DISABLE_GLOBAL_AGENT"] == "1"
