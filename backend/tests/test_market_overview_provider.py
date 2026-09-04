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
        assert item["sparkline"] == [{"timestamp": "2026-09-02T09:20:00+07:00", "value": 101, "reference": 100}]
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
    assert result["availability"] == "AVAILABLE"


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
async def test_breadth_refresh_is_background_only_and_never_blocks_the_payload():
    provider = FiinQuantProvider(username="test", password="test", max_symbols=33)
    provider._session = _Session()
    provider._is_connected = True
    provider._market_is_active = lambda: False

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
