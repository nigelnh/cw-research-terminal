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


class _Session:
    is_login = True
    def TickerList(self, ticker=None): return ["AAA", "BBB"] if ticker else ["AAA", "BBB", "CAAA2601"]
    def MarketBreadth(self): return _Breadth()
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
    assert result["top_cw_volume"][0]["symbol"] == "CAAA2601"
    assert result["cw_scope"] == "HOSE covered warrants"
    assert result["source"] == "FIINQUANT"
