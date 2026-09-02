import pytest

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
    def TickerList(self, ticker=None): return ["AAA", "BBB"] if ticker else ["AAA", "BBB", "CAAA2601"]
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
    assert result["cw_scope"] == "HOSE covered warrants"
    assert result["source"] == "FIINQUANT"


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
