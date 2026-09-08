import pytest
from unittest.mock import AsyncMock

from app.market_data.providers.fiinquant_provider import FiinQuantProvider


class _Result:
    def __init__(self, rows): self.rows = rows
    def get_data(self):
        class Frame:
            def __init__(self, rows): self.rows = rows
            def to_dict(self, orient=None): return list(self.rows)
        return Frame(self.rows)


class _PriceStatistics:
    def get_ceilingfloor(self, tickers, from_date, to_date):
        return _Result([{"ticker": symbol, "timestamp": from_date, "ceilingValue": 110, "floorValue": 90} for symbol in tickers])

    def get_overview(self, tickers, time_filter, from_date, to_date):
        # AAA up ~2%, BBB down ~2% (drives constituent breadth + volume leaders).
        return _Result([{
            "ticker": s, "timestamp": f"{from_date} 10:00",
            "totalMatchVolume": 20.0 if s == "AAA" else 15.0,
            "totalMatchValue": 2000.0 if s == "AAA" else 1500.0,
            "percentPriceChange": 0.02 if s == "AAA" else -0.02,
        } for s in tickers])


class _BasicInfor:
    def __init__(self, tickers): self.tickers = tickers
    def get(self):
        return _Result([{
            "ticker": symbol, "organizationName": f"{symbol} Corporation",
            "organizationShortName": symbol, "exchangeCode": "hose",
        } for symbol in self.tickers])


class _Session:
    is_login = True
    basic_calls = 0
    # Breadth is computed from these constituents (MarketBreadth is not licensed).
    _GROUPS = {"VNINDEX": ["AAA", "BBB"], "VN30": ["AAA", "BBB"],
              "VNFINLEAD": ["AAA"], "VNDIAMOND": ["BBB"]}
    def TickerList(self, ticker):
        return list(self._GROUPS[ticker])
    def MarketBreadth(self):
        raise AssertionError("MarketBreadth is not licensed and must not be called")
    def PriceStatistics(self): return _PriceStatistics()
    def BasicInfor(self, tickers):
        self.basic_calls += 1
        return _BasicInfor(tickers)
    def Fetch_Trading_Data(self, *, tickers, by, **kwargs):
        rows = []
        for symbol in tickers:
            rows.append({"ticker": symbol, "timestamp": "2026-09-01", "close": 100, "volume": 10, "value": 1000})
            rows.append({"ticker": symbol, "timestamp": "2026-09-02", "close": 102, "volume": 20 if symbol == "AAA" else 15, "value": 2000})
        return _Result(rows)


@pytest.mark.asyncio
async def test_overview_queries_intraday_in_explicit_ict_not_sdk_host_clock(monkeypatch):
    from datetime import datetime
    from app.market_data.market_session import market_session, VN_TZ
    monkeypatch.setattr(market_session, "get_vn_now", lambda: datetime(2026, 9, 2, 9, 28, tzinfo=VN_TZ))

    class MorningSession(_Session):
        def Fetch_Trading_Data(self, *, tickers, by, **kwargs):
            if by == "5m":
                assert "period" not in kwargs
                assert kwargs["from_date"] == "2026-09-02 09:00"
                assert kwargs["to_date"] == "2026-09-02 09:28"
                assert kwargs["lasted"] is True
                assert kwargs["realtime"] is False
                return _Result([{"ticker": symbol, "timestamp": "2026-09-02 09:20",
                                 "close": 101, "volume": 7, "value": 700} for symbol in tickers])
            result = super().Fetch_Trading_Data(tickers=tickers, by=by, **kwargs)
            for row in result.rows:
                if row["timestamp"] == "2026-09-02":
                    row["timestamp"] = "2026-09-02 09:27"
            return result

    provider = FiinQuantProvider(username="test", password="test", max_symbols=33)
    provider._session = MorningSession()
    provider._is_connected = True
    result = await provider.get_market_overview([])
    for item in result["indices"]:
        assert item["value"] == 102  # newer daily snapshot beats older 5m close
        assert item["as_of"] == "2026-09-02T09:27:00+07:00"
        assert item["sparkline"] == [{"timestamp": "2026-09-02T09:20:00+07:00", "value": 101, "reference": 100, "volume": 7}]
        assert item["update_mode"] == "POLLED"
        assert item["provenance"]["sparkline"]["timeframe"] == "5m"


@pytest.mark.asyncio
async def test_overview_after_hours_queries_the_observed_session_not_today(monkeypatch):
    from datetime import datetime
    from app.market_data.market_session import market_session, VN_TZ
    monkeypatch.setattr(market_session, "get_vn_now", lambda: datetime(2026, 9, 3, 8, 30, tzinfo=VN_TZ))

    class OvernightSession(_Session):
        def Fetch_Trading_Data(self, *, by, **kwargs):
            if by == "5m":
                assert kwargs["from_date"] == "2026-09-02 09:00"
                assert kwargs["to_date"] == "2026-09-02 15:00"
            return super().Fetch_Trading_Data(by=by, **kwargs)
    provider = FiinQuantProvider(username="test", password="test", max_symbols=33)
    provider._session = OvernightSession()
    provider._is_connected = True
    await provider.get_market_overview([])


@pytest.mark.asyncio
async def test_overview_uses_snapshot_reads_without_changing_stream_subscriptions():
    provider = FiinQuantProvider(username="test", password="test", max_symbols=33)
    provider._session = _Session()
    provider._is_connected = True
    provider._market_is_active = lambda: False
    before = provider.get_active_subscriptions()

    await provider._refresh_index_breadth()  # the slow HOSE sweep runs in the background
    result = await provider.get_market_overview(["CAAA2601"])

    assert provider.get_active_subscriptions() == before
    assert [item["symbol"] for item in result["indices"]] == ["VN30", "VNINDEX", "VNFINLEAD", "VNDIAMOND"]
    assert result["indices"][0]["value"] == 102
    assert result["indices"][0]["change_percent"] == pytest.approx(2)
    # VN30 group = {AAA up, BBB down} from get_overview's percentPriceChange.
    assert result["indices"][0]["advancing"] == 1
    assert result["indices"][0]["declining"] == 1
    assert result["indices"][0]["provenance"]["breadth"]["source"] == "DERIVED_CONSTITUENTS"
    assert result["top_stock_volume"][0]["symbol"] == "AAA"
    assert result["top_stock_volume"][0]["market_state"] == "UP"
    assert result["top_cw_volume"][0]["symbol"] == "CAAA2601"
    assert result["cw_scope"] == "active CW registry"
    assert result["source"] == "FIINQUANT"
    # Assert the components this fixture actually determines. Overall availability is NOT
    # one of them: an index card needs intraday bars to be AVAILABLE, and between the 08:00
    # rollover and the first bars after the 09:00 open the provider asks for an inverted
    # window (09:00..now) and legitimately gets none - so the card is PARTIAL and so is the
    # payload. Asserting AVAILABLE unconditionally made this pass or fail by the hour.
    components = result["components"]
    assert components["top_stock_volume"] == "AVAILABLE"
    assert components["top_cw_volume"] == "AVAILABLE"
    assert components["breadth"] == "AVAILABLE"
    assert components["bands"] == "AVAILABLE"
    assert result["availability"] in {"AVAILABLE", "PARTIAL"}


@pytest.mark.asyncio
async def test_overview_ignores_preopen_zero_reset_and_normalizes_vietnam_time():
    class ResetSession(_Session):
        def Fetch_Trading_Data(self, *, tickers, by, **kwargs):
            result = super().Fetch_Trading_Data(tickers=tickers, by=by, **kwargs)
            result.rows.extend({"ticker": symbol, "timestamp": "2026-09-03 08:22",
                                "close": 0, "volume": 0, "value": 0} for symbol in tickers)
            return result

    provider = FiinQuantProvider(username="test", password="test", max_symbols=33)
    provider._session = ResetSession()
    provider._is_connected = True
    result = await provider.get_market_overview(["CAAA2601"])
    for item in result["indices"] + result["top_stock_volume"] + result["top_cw_volume"]:
        assert item["as_of"] == "2026-09-02T00:00:00+07:00"
        assert item.get("value", item.get("price")) == 102
    assert result["top_cw_volume"][0]["market_state"] == "UP"


@pytest.mark.asyncio
async def test_cw_ranking_falls_back_to_the_last_session_after_the_close():
    """FiinQuant lags the CW 1d bar after the close; the panel shows the last session
    (tagged with its real as_of) instead of going empty."""
    class GappedSession(_Session):
        def Fetch_Trading_Data(self, *, tickers, by, **kwargs):
            result = super().Fetch_Trading_Data(tickers=tickers, by=by, **kwargs)
            # No current-session (2026-09-02) row for the CW — only the prior day.
            result.rows = [row for row in result.rows
                           if not (row["ticker"] == "CAAA2601" and row["timestamp"] == "2026-09-02")]
            return result

    provider = FiinQuantProvider(username="test", password="test", max_symbols=33)
    provider._session = GappedSession()
    provider._is_connected = True
    result = await provider.get_market_overview(["CAAA2601"])
    assert result["top_cw_volume"][0]["symbol"] == "CAAA2601"
    assert result["top_cw_volume"][0]["as_of"] == "2026-09-01T00:00:00+07:00"
    assert result["components"]["top_cw_volume"] == "AVAILABLE"
    # Breadth / stock leaders are the slow background sweep — never refreshed here.
    assert result["components"]["breadth"] == "UNAVAILABLE"
    assert result["top_stock_volume"] == []
    for item in result["indices"]:
        assert item["advancing"] is None


@pytest.mark.asyncio
async def test_cw_leader_color_survives_a_week_long_quiet_stretch(monkeypatch):
    """A thinly-traded CW can go well over a week between prints. If the daily-bar
    lookback is too short, the leaders panel finds a "current" bar but no PRIOR one to
    compare against, so `market_state` falls to UNAVAILABLE and the row renders with no
    color at all (the bug this pins: live prod showed 4/5 CW leaders uncolored)."""
    from datetime import datetime
    from app.market_data.market_session import market_session, VN_TZ
    monkeypatch.setattr(market_session, "get_vn_now", lambda: datetime(2026, 9, 4, 20, 0, tzinfo=VN_TZ))

    class SparseSession(_Session):
        def Fetch_Trading_Data(self, *, tickers, by, **kwargs):
            result = super().Fetch_Trading_Data(tickers=tickers, by=by, **kwargs)
            if by != "1d":
                return result
            # CAAA2601 last traded 2026-08-20, then not again until 2026-09-03 - an
            # 11-day gap. A 6-day lookback from "today" (2026-09-04) would miss the
            # 08-20 print entirely and leave no prior close to compare against.
            result.rows = [row for row in result.rows if row["ticker"] != "CAAA2601"]
            result.rows += [
                # 100 -> 105: up, but clear of the mock's ceiling/floor (110/90) so this
                # exercises the plain price-vs-reference UP branch, not CEILING.
                {"ticker": "CAAA2601", "timestamp": "2026-08-20", "close": 100, "volume": 500, "value": 50_000},
                {"ticker": "CAAA2601", "timestamp": "2026-09-03", "close": 105, "volume": 900, "value": 99_000},
            ]
            from_date = kwargs.get("from_date")
            if from_date:
                result.rows = [row for row in result.rows if row["timestamp"] >= from_date]
            return result

    provider = FiinQuantProvider(username="test", password="test", max_symbols=33)
    provider._session = SparseSession()
    provider._is_connected = True
    result = await provider.get_market_overview(["CAAA2601"])
    row = result["top_cw_volume"][0]
    assert row["symbol"] == "CAAA2601"
    assert row["price"] == 105
    assert row["reference"] == 100
    assert row["market_state"] == "UP"


@pytest.mark.asyncio
async def test_breadth_refresh_is_background_only_and_never_blocks_the_payload():
    provider = FiinQuantProvider(username="test", password="test", max_symbols=33)
    provider._session = _Session()
    provider._is_connected = True
    provider._market_is_active = lambda: False
    # Off-session the overview TTL stretches to the next session open (real wall-clock
    # value) - pin it small so "force a rebuild" below is deterministic regardless of
    # when this test happens to run.
    provider._seconds_to_next_session = lambda: 1.0

    first = await provider.get_market_overview(["CAAA2601"])
    assert first["indices"][0]["advancing"] is None          # not computed yet
    assert first["top_stock_volume"] == []

    await provider._refresh_index_breadth()
    provider._overview_cache_at = 0.0                          # force a rebuild
    second = await provider.get_market_overview(["CAAA2601"])
    assert second["indices"][0]["advancing"] == 1             # VN30: AAA up
    assert second["indices"][0]["declining"] == 1             # VN30: BBB down
    assert second["top_stock_volume"][0]["symbol"] == "AAA"


@pytest.mark.asyncio
async def test_overview_cache_survives_a_multihour_gap_outside_trading_hours():
    """Nothing changes until the market reopens, so a SETTLED overview (background breadth
    sweep already done) must not re-hit FiinQuant on some short fixed timer while closed -
    only once the next session actually nears."""
    class CountingSession(_Session):
        calls = 0
        def Fetch_Trading_Data(self, *, tickers, by, **kwargs):
            CountingSession.calls += 1
            return super().Fetch_Trading_Data(tickers=tickers, by=by, **kwargs)

    provider = FiinQuantProvider(username="test", password="test", max_symbols=33)
    provider._session = CountingSession()
    provider._is_connected = True
    provider._market_is_active = lambda: False
    provider._seconds_to_next_session = lambda: 6 * 3600  # e.g. overnight, next open in 6h
    await provider._refresh_index_breadth()  # settle stock leaders before the first build

    await provider.get_market_overview(["CAAA2601"])
    calls_after_first = CountingSession.calls
    assert calls_after_first > 0

    # An hour "passes" - the old fixed 300s TTL would have forced a rebuild well before now.
    provider._overview_cache_at -= 3600
    await provider.get_market_overview(["CAAA2601"])
    assert CountingSession.calls == calls_after_first  # still served from cache


@pytest.mark.asyncio
async def test_overview_cache_stays_short_lived_until_stock_leaders_settle():
    """An overview built before the background breadth sweep finishes (stock leaders still
    empty) must NOT get the long off-session TTL - otherwise "Top Stock Trading Volume"
    would stay stuck empty for the rest of a closed weekend, since nothing would ever ask
    FiinQuant for it again. It should keep retrying on the short TTL until it settles."""
    class CountingSession(_Session):
        calls = 0
        def Fetch_Trading_Data(self, *, tickers, by, **kwargs):
            CountingSession.calls += 1
            return super().Fetch_Trading_Data(tickers=tickers, by=by, **kwargs)

    provider = FiinQuantProvider(username="test", password="test", max_symbols=33)
    provider._session = CountingSession()
    provider._is_connected = True
    provider._market_is_active = lambda: False
    provider._seconds_to_next_session = lambda: 6 * 3600  # e.g. overnight, next open in 6h

    # No _refresh_index_breadth() yet - stock leaders are empty, same as right after a
    # cold restart, before the background sweep has had a chance to finish.
    first = await provider.get_market_overview(["CAAA2601"])
    assert first["components"]["top_stock_volume"] == "UNAVAILABLE"
    calls_after_first = CountingSession.calls

    # The background sweep finishes moments later (as it does in prod, ~20-30s in).
    await provider._refresh_index_breadth()

    # Only a few seconds pass - the old fixed 300s TTL, and a naively-stretched off-session
    # TTL, would BOTH still be serving the incomplete cached snapshot right now.
    provider._overview_cache_at -= 20
    second = await provider.get_market_overview(["CAAA2601"])
    assert CountingSession.calls > calls_after_first  # retried, did not wait for next session
    assert second["components"]["top_stock_volume"] == "AVAILABLE"
    assert second["top_stock_volume"][0]["symbol"] == "AAA"

    # Now that it's settled, a later request survives a real multi-hour gap without refetching.
    calls_after_second = CountingSession.calls
    provider._overview_cache_at -= 3600
    await provider.get_market_overview(["CAAA2601"])
    assert CountingSession.calls == calls_after_second


@pytest.mark.asyncio
async def test_overview_cache_stays_short_lived_until_the_chart_covers_the_open(monkeypatch):
    """An overview whose intraday fetch hiccuped and came back starting well after 09:00
    (confirmed live: production served a chart starting ~11:05, missing the whole morning)
    must NOT get the long off-session TTL either - same trap as stock leaders, different
    field. Should keep retrying on the short TTL until a chart covering the open lands."""
    from datetime import datetime
    from app.market_data.market_session import market_session, VN_TZ
    monkeypatch.setattr(market_session, "get_vn_now", lambda: datetime(2026, 9, 2, 15, 5, tzinfo=VN_TZ))

    class LateOpenSession(_Session):
        calls = 0
        starts_at_open = False

        def Fetch_Trading_Data(self, *, tickers, by, **kwargs):
            LateOpenSession.calls += 1
            if by == "5m":
                start = "09:00" if LateOpenSession.starts_at_open else "11:05"
                return _Result([{"ticker": symbol, "timestamp": f"2026-09-02 {start}",
                                 "close": 101, "volume": 7, "value": 700} for symbol in tickers])
            return super().Fetch_Trading_Data(tickers=tickers, by=by, **kwargs)

    provider = FiinQuantProvider(username="test", password="test", max_symbols=33)
    provider._session = LateOpenSession()
    provider._is_connected = True
    provider._market_is_active = lambda: False
    provider._seconds_to_next_session = lambda: 6 * 3600
    await provider._refresh_index_breadth()  # settle stock leaders so only the chart matters

    first = await provider.get_market_overview([])
    assert first["indices"][0]["sparkline"][0]["timestamp"] == "2026-09-02T11:05:00+07:00"
    calls_after_first = LateOpenSession.calls

    # A clean fetch (covering the open) lands moments later.
    LateOpenSession.starts_at_open = True
    provider._overview_cache_at -= 20  # only a few seconds pass
    second = await provider.get_market_overview([])
    assert LateOpenSession.calls > calls_after_first  # retried, did not wait for next session
    assert second["indices"][0]["sparkline"][0]["timestamp"] == "2026-09-02T09:00:00+07:00"

    # Now that it's settled, a later request survives a real multi-hour gap without refetching.
    calls_after_second = LateOpenSession.calls
    provider._overview_cache_at -= 3600
    await provider.get_market_overview([])
    assert LateOpenSession.calls == calls_after_second


@pytest.mark.asyncio
async def test_overview_cache_still_rebuilds_once_the_next_session_is_close():
    """The stretched TTL is bounded by the real next-session time, not infinite."""
    class CountingSession(_Session):
        calls = 0
        def Fetch_Trading_Data(self, *, tickers, by, **kwargs):
            CountingSession.calls += 1
            return super().Fetch_Trading_Data(tickers=tickers, by=by, **kwargs)

    provider = FiinQuantProvider(username="test", password="test", max_symbols=33)
    provider._session = CountingSession()
    provider._is_connected = True
    provider._market_is_active = lambda: False
    provider._seconds_to_next_session = lambda: 10.0  # market opens very soon
    await provider._refresh_index_breadth()  # settle stock leaders before the first build

    await provider.get_market_overview(["CAAA2601"])
    calls_after_first = CountingSession.calls

    provider._overview_cache_at -= 3600  # far older than the 10s-away next session
    await provider.get_market_overview(["CAAA2601"])
    assert CountingSession.calls > calls_after_first  # rebuilt


@pytest.mark.asyncio
async def test_stock_profiles_are_normalized_cached_and_do_not_consume_stream_slots():
    provider = FiinQuantProvider(username="test", password="test", max_symbols=33)
    provider._session = _Session()
    provider._is_connected = True
    before = provider.get_active_subscriptions()

    first = await provider.get_stock_profiles(["hpg", "VPB", "HPG"])
    second = await provider.get_stock_profiles(["VPB", "HPG"])

    assert first == [
        {"symbol": "HPG", "name": "HPG Corporation", "short_name": "HPG", "exchange": "HOSE"},
        {"symbol": "VPB", "name": "VPB Corporation", "short_name": "VPB", "exchange": "HOSE"},
    ]
    assert second == first
    assert provider._session.basic_calls == 1
    assert provider.get_active_subscriptions() == before


@pytest.mark.asyncio
async def test_stock_profiles_accept_documented_basicinfor_field_names_and_short_aliases():
    class DocumentedSession(_Session):
        def BasicInfor(self, tickers):
            self.basic_calls += 1

            class DocumentedBasicInfor:
                def get(inner_self):
                    return _Result([
                        {
                            "ticker": tickers[0],
                            "companyName": "Hoa Phat Group Joint Stock Company",
                            "shortName": "Hoa Phat",
                            "exchange": "hose",
                            # Legacy fields must not override the documented names.
                            "organizationName": "Legacy Name",
                            "organizationShortName": "Legacy Short",
                            "exchangeCode": "hnx",
                        },
                        {
                            "ticker": tickers[1],
                            "companyName": "Vietnam Prosperity Bank",
                            "companyShortName": "VPBank",
                            "exchange": "hose",
                        },
                    ])

            return DocumentedBasicInfor()

    provider = FiinQuantProvider(username="test", password="test", max_symbols=33)
    provider._session = DocumentedSession()
    provider._is_connected = True

    result = await provider.get_stock_profiles(["HPG", "VPB"])

    assert result == [
        {
            "symbol": "HPG",
            "name": "Hoa Phat Group Joint Stock Company",
            "short_name": "Hoa Phat",
            "exchange": "HOSE",
        },
        {
            "symbol": "VPB",
            "name": "Vietnam Prosperity Bank",
            "short_name": "VPBank",
            "exchange": "HOSE",
        },
    ]


@pytest.mark.asyncio
async def test_session_reference_data_uses_previous_close_and_requested_session_bands():
    provider = FiinQuantProvider(username="test", password="test", max_symbols=33)
    provider._session = _Session()
    provider._is_connected = True

    from datetime import date

    result = await provider.get_session_reference_data(["AAA", "CAAA2601"], date(2026, 9, 2))

    assert result["AAA"] == {
        "session_date": "2026-09-02",
        "reference_price": 100.0,
        "ceiling_price": 110.0,
        "floor_price": 90.0,
    }
    assert result["CAAA2601"]["reference_price"] == 100.0


@pytest.mark.asyncio
async def test_overview_returns_partial_payload_when_optional_reads_fail():
    class PartialSession(_Session):
        def Fetch_Trading_Data(self, *, by, **kwargs):
            if by == "5m":
                raise RuntimeError("intraday unavailable")
            return super().Fetch_Trading_Data(by=by, **kwargs)

        def TickerList(self, ticker):
            raise RuntimeError("constituents unavailable")

    provider = FiinQuantProvider(username="test", password="test", max_symbols=33)
    provider._session = PartialSession()
    provider._is_connected = True
    provider._market_is_active = lambda: False

    result = await provider.get_market_overview(["CAAA2601"])

    assert result["availability"] == "PARTIAL"
    assert result["components"]["breadth"] == "UNAVAILABLE"
    assert result["indices"][0]["value"] == 102
    assert result["indices"][0]["availability"] == "PARTIAL"
    assert result["indices"][0]["partial_reasons"] == ["INTRADAY_UNAVAILABLE", "BREADTH_UNAVAILABLE"]
    assert result["indices"][0]["sparkline"] == []
    assert result["top_cw_volume"][0]["symbol"] == "CAAA2601"


@pytest.mark.asyncio
async def test_overview_returns_truthfully_stale_cache_when_reconnect_fails():
    provider = FiinQuantProvider(username="test", password="test", max_symbols=33)
    provider._session = None
    provider._is_connected = False
    provider._market_is_active = lambda: False
    provider.connect = AsyncMock(return_value=False)
    provider._overview_cache_at = 0.0
    provider._overview_cache = {
        "indices": [{
            "symbol": "VNINDEX",
            "value": 1832.12,
            "availability": "AVAILABLE",
            "stale": False,
        }],
        "top_stock_volume": [{"symbol": "HPG", "volume": 10}],
        "top_cw_volume": [],
        "as_of": "2026-09-02T15:00:00+07:00",
        "source": "FIINQUANT",
        "availability": "AVAILABLE",
        "components": {"indices": "AVAILABLE", "top_stock_volume": "AVAILABLE"},
    }

    result = await provider.get_market_overview(["CHPG2617"])

    assert result["source"] == "FIINQUANT_CACHE"
    assert result["availability"] == "PARTIAL"
    assert result["freshness"] == "STALE"
    assert result["stale"] is True
    assert result["market_session_active"] is False
    assert result["cache_age_seconds"] >= 0
    assert result["indices"][0]["availability"] == "PARTIAL"
    assert result["indices"][0]["stale"] is True
    assert result["top_stock_volume"][0]["stale"] is True
    assert result["components"] == {
        "indices": "PARTIAL",
        "top_stock_volume": "PARTIAL",
        "provider": "UNAVAILABLE",
    }
    # Serving stale data must not poison the canonical cache for a later reconnect.
    assert provider._overview_cache["source"] == "FIINQUANT"
    assert provider._overview_cache["indices"][0]["availability"] == "AVAILABLE"
    provider.connect.assert_awaited_once()


@pytest.mark.asyncio
async def test_overview_raises_when_reconnect_fails_without_usable_cache():
    provider = FiinQuantProvider(username="test", password="test", max_symbols=33)
    provider._session = None
    provider._is_connected = False
    provider.connect = AsyncMock(return_value=False)

    with pytest.raises(RuntimeError, match="market overview is unavailable"):
        await provider.get_market_overview([])
