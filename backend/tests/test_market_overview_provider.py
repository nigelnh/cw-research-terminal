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


class _Breadth:
    def get(self, tickers):
        return _Result([{
            "comGroupCode": symbol, "tradingDate": "2026-09-02T14:00:00+07:00",
            "totalStockUpPrice": 10, "totalStockOverCeiling": 1,
            "totalStockNoChangePrice": 3, "totalStockDownPrice": 8,
            "totalStockUnderFloor": 2,
        } for symbol in tickers])


class _PriceStatistics:
    def get_ceilingfloor(self, tickers, from_date, to_date):
        return _Result([{"ticker": symbol, "timestamp": from_date, "ceilingValue": 110, "floorValue": 90} for symbol in tickers])


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
    def TickerList(self, ticker):
        assert ticker == "VNINDEX"
        return ["AAA", "BBB"]
    def MarketBreadth(self): return _Breadth()
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
async def test_overview_uses_snapshot_reads_without_changing_stream_subscriptions():
    provider = FiinQuantProvider(username="test", password="test", max_symbols=33)
    provider._session = _Session()
    provider._is_connected = True
    provider._market_is_active = lambda: False
    before = provider.get_active_subscriptions()

    result = await provider.get_market_overview(["CAAA2601"])

    assert provider.get_active_subscriptions() == before
    assert [item["symbol"] for item in result["indices"]] == ["VN30", "VNINDEX", "VNFINLEAD", "VNDIAMOND"]
    assert result["indices"][0]["value"] == 102
    assert result["indices"][0]["change_percent"] == pytest.approx(2)
    assert result["indices"][0]["advancing"] == 10
    assert result["top_stock_volume"][0]["symbol"] == "AAA"
    assert result["top_stock_volume"][0]["market_state"] == "UP"
    assert result["top_cw_volume"][0]["symbol"] == "CAAA2601"
    assert result["cw_scope"] == "active CW registry"
    assert result["source"] == "FIINQUANT"
    assert result["availability"] == "AVAILABLE"


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

        def MarketBreadth(self):
            raise RuntimeError("breadth unavailable")

    provider = FiinQuantProvider(username="test", password="test", max_symbols=33)
    provider._session = PartialSession()
    provider._is_connected = True
    provider._market_is_active = lambda: False

    result = await provider.get_market_overview(["CAAA2601"])

    assert result["availability"] == "PARTIAL"
    assert result["components"]["breadth"] == "UNAVAILABLE"
    assert result["indices"][0]["value"] == 102
    assert result["indices"][0]["availability"] == "PARTIAL"
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
