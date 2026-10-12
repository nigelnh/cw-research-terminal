"""A symbol off the realtime stream reads the price board during a session.

The stream carries the configured universe (VN30, the warrant underlyings, the warrants).
On 2026-10-12 the AI was asked about NVL during ATO: NVL is not on the stream, so the
resolver returned an all-null quote noted "awaiting a trade in the new session", and the
model told the user NVL "hasn't printed a trade yet". Nothing had looked.
"""

from __future__ import annotations

import time
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from app.ai.tools import market_tools
from app.main import app
from app.market_data import market_snapshot_resolver as resolver_module
from app.market_data.market_snapshot_resolver import MarketSnapshotResolver, market_snapshot_resolver
from app.market_data.market_state import MarketState
from app.market_data.market_subscription_manager import subscription_manager
from app.market_data.providers.vnstock_provider import VnstockProvider
from app.market_data.trading_calendar import VN_TZ

SESSION = date(2026, 10, 12)  # a Monday; Friday 2026-10-09 is the last completed session


@pytest.fixture(autouse=True)
def no_live_quotes(monkeypatch):
    """The resolver reads the process-wide MarketState, which other tests fill with quotes
    for today's real session - and this file's session is a real date too."""
    monkeypatch.setattr(resolver_module, "market_state", MarketState())
IN_SESSION = datetime(2026, 10, 12, 10, 0, tzinfo=VN_TZ)
STAMP_MS = int(datetime(2026, 10, 12, 9, 59, 58, tzinfo=VN_TZ).timestamp() * 1000)


def nvl_row(**over):
    """A KBS price-board row as `Trading.price_board` returns it."""
    return {
        "symbol": "NVL", "TD": "12/10/2026", "time": STAMP_MS,
        "close_price": 15300, "reference_price": 15000, "ceiling_price": 16050,
        "floor_price": 13950, "open_price": 15050, "high_price": 15400,
        "low_price": 15000, "average_price": 15210, "price_change": 300,
        "percent_change": 2.0, "volume_accumulated": 4_120_300,
        "total_value": 62_668_000_000, "bid_price_1": "15250.0", "bid_vol_1": 41_000,
        "ask_price_1": "15300.0", "ask_vol_1": 12_500, **over,
    }


class Board:
    """The provider's board fetcher: records each call's symbols."""

    def __init__(self, rows):
        self.rows = {row["symbol"]: row for row in rows}
        self.calls: list[list[str]] = []

    def __call__(self, symbols):
        self.calls.append(list(symbols))
        return [self.rows[s] for s in symbols if s in self.rows]


def provider(board) -> VnstockProvider:
    p = VnstockProvider(board_fetcher=board)
    p._request_floor = 0
    return p


# --------------------------------------------------------------------------- provider #

@pytest.mark.asyncio
async def test_a_board_row_becomes_this_sessions_quote_in_raw_vnd():
    quotes = await provider(Board([nvl_row()])).get_board_quotes(["nvl"], SESSION)

    q = quotes["NVL"]
    assert q["last_price"] == 15300
    assert (q["reference_price"], q["ceiling_price"], q["floor_price"]) == (15000, 16050, 13950)
    assert q["total_volume"] == 4_120_300
    assert q["trading_value"] == 62_668_000_000
    assert q["price_change"] == 300
    assert q["price_change_percent"] == pytest.approx(0.02)
    assert (q["bid1_price"], q["bid1_quantity"]) == (15250, 41_000)
    assert (q["ask1_price"], q["ask1_quantity"]) == (15300, 12_500)
    assert q["bid2_price"] is q["bid2_quantity"] is None
    assert q["session_date"] == "2026-10-12"
    assert q["as_of"].startswith("2026-10-12T09:59:58")


@pytest.mark.asyncio
async def test_a_row_for_another_session_is_no_quote():
    quotes = await provider(Board([nvl_row(TD="09/10/2026")])).get_board_quotes(["NVL"], SESSION)
    assert quotes == {}


@pytest.mark.asyncio
async def test_zero_volume_is_no_trade_but_the_bands_stand():
    # KBS writes 0 for what it does not have: before the first match, and always for a
    # covered warrant's close and volume.
    row = nvl_row(close_price=0, volume_accumulated=0, total_value=0, open_price=0,
                  high_price=0, low_price=0, average_price=0, price_change=0, percent_change=0)
    q = (await provider(Board([row])).get_board_quotes(["NVL"], SESSION))["NVL"]
    assert q["last_price"] is q["total_volume"] is q["price_change"] is None
    assert q["open_price"] is q["trading_value"] is None
    assert q["reference_price"] == 15000
    assert q["bid1_price"] == 15250


@pytest.mark.asyncio
async def test_each_symbols_answer_is_kept_briefly_even_when_the_board_has_no_row():
    board = Board([nvl_row()])
    p = provider(board)
    await p.get_board_quotes(["NVL", "XYZ"], SESSION)
    await p.get_board_quotes(["XYZ", "NVL"], SESSION)
    assert board.calls == [["NVL", "XYZ"]]

    # Only what has expired is asked for again.
    stamp, row = p._board_quote_cache["XYZ"]
    p._board_quote_cache["XYZ"] = (stamp - p._BOARD_QUOTE_TTL - 1, row)
    await p.get_board_quotes(["NVL", "XYZ"], SESSION)
    assert board.calls[-1] == ["XYZ"]


@pytest.mark.asyncio
async def test_the_board_quote_read_leaves_the_streams_board_alone():
    board = Board([nvl_row()])
    p = provider(board)
    p._board_cache_at = time.monotonic()
    p._board_cache_requested = {"HPG"}
    p._board_cache = {"HPG": {"symbol": "HPG"}}

    await p.get_board_quotes(["NVL"], SESSION)

    assert p._board_cache == {"HPG": {"symbol": "HPG"}}
    assert p._board_cache_requested == {"HPG"}


@pytest.mark.asyncio
async def test_a_failed_board_read_blocks_only_its_own_scope():
    def down(_symbols):
        raise ConnectionError("connection error")

    p = provider(down)
    with pytest.raises(ConnectionError):
        await p.get_board_quotes(["NVL"], SESSION)
    assert p._access.blocked("board_quote")
    assert not p._access.blocked("stream")


# --------------------------------------------------------------------------- resolver #

def resolver(fetch, tracked=frozenset({"HPG"})) -> MarketSnapshotResolver:
    r = MarketSnapshotResolver()
    r.set_board_source(fetch, lambda symbol: symbol in tracked)
    return r


class Fetch:
    def __init__(self, quotes=None, error: Exception | None = None):
        self.quotes = quotes or {}
        self.error = error
        self.calls: list[tuple[list[str], date]] = []

    async def __call__(self, symbols, session):
        self.calls.append((list(symbols), session))
        if self.error is not None:
            raise self.error
        return {s: q for s, q in self.quotes.items() if s in symbols}


async def board_quote(symbol: str = "NVL", **over) -> dict:
    rows = Board([nvl_row(symbol=symbol, **over)])
    return (await provider(rows).get_board_quotes([symbol], SESSION))[symbol]


@pytest.mark.asyncio
async def test_an_off_stream_symbol_in_session_gets_the_board_quote():
    fetch = Fetch({"NVL": await board_quote()})
    row = (await resolver(fetch).resolve_rows(["NVL"], now=IN_SESSION))[0]

    assert fetch.calls == [(["NVL"], SESSION)]
    assert row.tracked_realtime is False
    wire = row.to_wire()
    assert (wire["Traded"], wire["Ref"], wire["Ceil"], wire["Floor"]) == (15.3, 15.0, 16.05, 13.95)
    assert wire["Total_Vol"] == 4_120_300
    assert wire["change"] == 0.3
    assert wire["ChangePercent"] == pytest.approx(0.02)
    assert (wire["Bid1_Prc"], wire["Ask1_Prc"]) == (15.25, 15.3)
    quote = wire["provenance"]["quote"]
    assert (quote["state"], quote["source"], quote["sessionDate"]) == (
        "SESSION_SNAPSHOT", "PRICE_BOARD", "2026-10-12")
    assert "not on the realtime stream" in quote["note"]
    assert wire["provenance"]["book"]["source"] == "PRICE_BOARD"
    assert wire["displayState"] == "SESSION_SNAPSHOT"
    assert wire["is_realtime_eligible"] is False


@pytest.mark.asyncio
async def test_a_symbol_on_the_stream_never_reads_the_board():
    fetch = Fetch({"HPG": await board_quote("HPG")})
    row = (await resolver(fetch).resolve_rows(["HPG"], now=IN_SESSION))[0]

    assert fetch.calls == []
    assert row.tracked_realtime is True
    assert row.quote_prov.source.value == "NONE"
    assert "awaiting a trade" in row.quote_prov.note


@pytest.mark.asyncio
async def test_an_unread_board_says_so_and_never_awaiting_a_trade():
    fetch = Fetch(error=TimeoutError())
    row = (await resolver(fetch).resolve_rows(["NVL"], now=IN_SESSION))[0]

    assert row.values.get("last_price") is None
    assert row.quote_prov.state.value == "UNAVAILABLE"
    assert row.quote_prov.note == "not on the realtime stream; the price board could not be read"
    assert row.book_prov.note == row.quote_prov.note


@pytest.mark.asyncio
async def test_no_board_row_says_so():
    row = (await resolver(Fetch()).resolve_rows(["NVL"], now=IN_SESSION))[0]
    assert row.quote_prov.note == "not on the realtime stream; no price-board row for this session"


@pytest.mark.asyncio
async def test_before_the_first_match_the_board_answers_no_trade_with_the_bands():
    quote = await board_quote(close_price=0, volume_accumulated=0, total_value=0, price_change=0)
    row = (await resolver(Fetch({"NVL": quote})).resolve_rows(["NVL"], now=IN_SESSION))[0]

    assert row.values["last_price"] is None
    assert row.quote_prov.state.value == "UNAVAILABLE"
    # The board looked: "no trade yet" is its answer here, unlike a quote nobody read.
    assert row.quote_prov.source.value == "PRICE_BOARD"
    assert row.quote_prov.note.startswith("no matched trade yet this session")
    assert row.values["reference_price"] == 15000
    assert row.reference_prov.session_date == "2026-10-12"
    assert row.book_prov.state.value == "SESSION_SNAPSHOT"


@pytest.mark.asyncio
async def test_an_index_is_never_sent_to_the_board():
    fetch = Fetch({"NVL": await board_quote()})
    rows = await resolver(fetch).resolve_rows(["VNINDEX", "NVL"], now=IN_SESSION)
    assert fetch.calls == [(["NVL"], SESSION)]
    assert rows[0].quote_prov.source.value == "NONE"


@pytest.mark.asyncio
async def test_off_session_the_board_is_not_read():
    fetch = Fetch({"NVL": await board_quote()})
    sunday = datetime(2026, 10, 11, 10, 0, tzinfo=VN_TZ)
    await resolver(fetch).resolve_rows(["NVL"], now=sunday)
    assert fetch.calls == []


# ------------------------------------------------------------------------------- AI #

class _FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return IN_SESSION.astimezone(tz) if tz else IN_SESSION


@pytest.mark.asyncio
async def test_the_ai_quote_for_nvl_in_session_is_the_board_quote(monkeypatch):
    fetch = Fetch({"NVL": await board_quote()})
    monkeypatch.setattr(resolver_module, "datetime", _FrozenDatetime)
    monkeypatch.setattr(market_snapshot_resolver, "_board_fetch", fetch)
    monkeypatch.setattr(market_snapshot_resolver, "_tracked", lambda symbol: symbol == "HPG")

    quote = await market_tools.get_quote("NVL")

    assert quote["status"] == "AVAILABLE"
    assert quote["last_price"] == 15300
    assert quote["data_source"] == "PRICE_BOARD"
    assert quote["tracked_realtime"] is False
    assert "not on the realtime stream" in quote["quote_note"]


@pytest.mark.asyncio
async def test_the_ai_is_told_why_an_unavailable_quote_is_empty(monkeypatch):
    monkeypatch.setattr(resolver_module, "datetime", _FrozenDatetime)
    monkeypatch.setattr(market_snapshot_resolver, "_board_fetch", Fetch(error=TimeoutError()))
    monkeypatch.setattr(market_snapshot_resolver, "_tracked", lambda symbol: symbol == "HPG")

    quote = await market_tools.get_quote("NVL")

    assert quote["status"] == "UNAVAILABLE"
    assert quote["data_source"] == "NONE"
    assert quote["quote_note"] == "not on the realtime stream; the price board could not be read"


def test_the_prompt_reads_no_trade_only_from_a_source_that_looked():
    from app.ai.ai_system_prompt import build_system_prompt

    text = build_system_prompt(
        latest_user_message="NVL now?", tool_results=[{"tool": "get_quote", "symbol": "NVL"}],
    )
    # The unconditional rule the model followed into "NVL hasn't traded yet".
    assert "If an instrument's last price is null during an OPEN session (no matched trade yet today)" not in text
    assert "ONLY when the quote's `data_source` observed this session" in text
    assert "`quote_note`" in text


# --------------------------------------------------------------------------- wiring #

def test_startup_wires_the_board_and_shutdown_unwires_it():
    with TestClient(app):
        assert market_snapshot_resolver._board_fetch == subscription_manager.provider.get_board_quotes
        assert market_snapshot_resolver._tracked == subscription_manager.is_in_server_universe
    assert market_snapshot_resolver._board_fetch is None
    assert market_snapshot_resolver._tracked is None
