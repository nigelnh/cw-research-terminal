"""
Unit tests for FiinQuant schema normalization helpers.
"""

from normalization_helpers import (
    normalize_fiinquant_price_to_raw_vnd,
    map_fiinquant_trade_to_canonical,
    map_fiinquant_bidask_to_canonical,
)


def test_normalize_price():
    assert normalize_fiinquant_price_to_raw_vnd(28500) == 28500.0
    assert normalize_fiinquant_price_to_raw_vnd("1350") == 1350.0
    assert normalize_fiinquant_price_to_raw_vnd(None) is None
    assert normalize_fiinquant_price_to_raw_vnd(float("nan")) is None


def test_map_trade_stock():
    raw_payload = {
        "Ticker": "HPG",
        "Close": 28500.0,
        "ReferencePrice": 28000.0,
        "Open": 28100.0,
        "High": 28600.0,
        "Low": 28050.0,
        "change": 500.0,
        "ChangePercent": 1.79,
        "TotalMatchVolume": 15420000,
        "TradingDate": "2026-08-24",
        "Timestamp": "14:28:15",
        "MarketStatus": "CONTINUOUS_TRADING",
    }
    canonical = map_fiinquant_trade_to_canonical(raw_payload)

    assert canonical["symbol"] == "HPG"
    assert canonical["isIndex"] is False
    assert canonical["lastPrice"] == 28500.0
    assert canonical["referencePrice"] == 28000.0
    assert canonical["openPrice"] == 28100.0
    assert canonical["priceChange"] == 500.0
    assert canonical["priceChangePercent"] == 1.79
    assert canonical["totalVolume"] == 15420000
    assert canonical["providerTimestamp"] == "2026-08-24 14:28:15"
    assert "receivedTimestamp" in canonical


def test_map_trade_cw():
    raw_payload = {
        "Ticker": "CFPT2401",
        "Close": 1450.0,
        "ReferencePrice": 1400.0,
        "TotalMatchVolume": 350000,
        "TradingDate": "2026-08-24",
        "Timestamp": "14:29:00",
    }
    canonical = map_fiinquant_trade_to_canonical(raw_payload)

    assert canonical["symbol"] == "CFPT2401"
    assert canonical["isIndex"] is False
    assert canonical["lastPrice"] == 1450.0
    assert canonical["referencePrice"] == 1400.0
    assert canonical["totalVolume"] == 350000


def test_map_trade_index():
    raw_payload = {
        "Ticker": "VNINDEX",
        "Close": 1285.45,
        "ReferencePrice": 1280.10,
        "change": 5.35,
        "ChangePercent": 0.42,
        "TradingDate": "2026-08-24",
        "Timestamp": "14:30:00",
    }
    canonical = map_fiinquant_trade_to_canonical(raw_payload)

    assert canonical["symbol"] == "VNINDEX"
    assert canonical["isIndex"] is True
    assert canonical["lastPrice"] == 1285.45


def test_map_bidask():
    raw_payload = {
        "Ticker": "CFPT2401",
        "TradingDate": "2026-08-24",
        "Timestamp": "14:29:50",
        "Spread": 10.0,
        "SpreadDelta": 0.0,
        "DepthImbalance": 0.15,
        "Best1Bid": 1440.0,
        "Best1BidVolume": 50000,
        "Best1Ask": 1450.0,
        "Best1AskVolume": 32000,
        "Best2Bid": 1430.0,
        "Best2BidVolume": 100000,
        "Best2Ask": 1460.0,
        "Best2AskVolume": 45000,
        "TotalBidVolume": 250000,
        "TotalAskVolume": 180000,
    }
    canonical = map_fiinquant_bidask_to_canonical(raw_payload)

    assert canonical["symbol"] == "CFPT2401"
    assert canonical["bid1Price"] == 1440.0
    assert canonical["bid1Quantity"] == 50000
    assert canonical["ask1Price"] == 1450.0
    assert canonical["ask1Quantity"] == 32000
    assert canonical["bid2Price"] == 1430.0
    assert canonical["bid2Quantity"] == 100000
    assert canonical["spread"] == 10.0
    assert canonical["totalBidVolume"] == 250000
