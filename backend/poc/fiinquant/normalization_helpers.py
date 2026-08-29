"""
FiinQuant Normalization Helpers
Pure schema mapping and unit conversion utilities for FiinQuant RealTimeData and BidAskData payloads.
Explicitly converts raw payloads to canonical cw-research-terminal representations.
"""

from typing import Dict, Any, Optional
import datetime


def normalize_fiinquant_price_to_raw_vnd(value: Any, is_index: bool = False) -> Optional[float]:
    """
    Normalizes FiinQuant price values.
    Index values (e.g. VNINDEX 1280.5) remain in index points.
    Equities and CWs: FiinQuant uses raw VND (e.g. 29500 VND or 1350 VND) or thousand-VND.
    This helper converts numeric values safely to canonical representation.
    """
    if value is None:
        return None
    try:
        val = float(value)
        if val != val:  # NaN check
            return None
        return val
    except (ValueError, TypeError):
        return None


def map_fiinquant_trade_to_canonical(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Maps a raw FiinQuant RealTimeData dictionary to canonical market quote properties.
    """
    ticker = str(raw.get("Ticker", "")).upper()
    is_index = ticker in {
        "VNINDEX", "VN30", "HNXINDEX", "UPCOMINDEX", "VN100", "VNMID", "VNSML", "VNALL"
    }

    last_price = normalize_fiinquant_price_to_raw_vnd(
        raw.get("Close") if raw.get("Close") is not None else raw.get("ClosePrice"),
        is_index=is_index
    )
    ref_price = normalize_fiinquant_price_to_raw_vnd(raw.get("ReferencePrice"), is_index=is_index)
    open_price = normalize_fiinquant_price_to_raw_vnd(raw.get("Open"), is_index=is_index)
    high_price = normalize_fiinquant_price_to_raw_vnd(raw.get("High"), is_index=is_index)
    low_price = normalize_fiinquant_price_to_raw_vnd(raw.get("Low"), is_index=is_index)
    
    change = normalize_fiinquant_price_to_raw_vnd(raw.get("change"), is_index=is_index)
    change_pct = normalize_fiinquant_price_to_raw_vnd(raw.get("ChangePercent"), is_index=is_index)
    
    total_volume = raw.get("TotalMatchVolume")
    if total_volume is not None:
        try:
            total_volume = int(total_volume)
        except (ValueError, TypeError):
            total_volume = None

    trading_date = raw.get("TradingDate")
    raw_timestamp = raw.get("Timestamp")
    provider_timestamp = f"{trading_date} {raw_timestamp}".strip() if trading_date or raw_timestamp else None

    return {
        "symbol": ticker,
        "isIndex": is_index,
        "lastPrice": last_price,
        "referencePrice": ref_price,
        "ceilingPrice": None,  # Not present directly in RealTimeData payload
        "floorPrice": None,    # Not present directly in RealTimeData payload
        "openPrice": open_price,
        "highPrice": high_price,
        "lowPrice": low_price,
        "priceChange": change,
        "priceChangePercent": change_pct,
        "totalVolume": total_volume,
        "marketStatus": raw.get("MarketStatus"),
        "providerTimestamp": provider_timestamp,
        "receivedTimestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


def map_fiinquant_bidask_to_canonical(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Maps a raw FiinQuant BidAskData dictionary to canonical depth & spread properties.
    """
    ticker = str(raw.get("Ticker", "")).upper()
    trading_date = raw.get("TradingDate")
    raw_timestamp = raw.get("Timestamp")
    provider_timestamp = f"{trading_date} {raw_timestamp}".strip() if trading_date or raw_timestamp else None

    def get_float(k: str) -> Optional[float]:
        v = raw.get(k)
        if v is None:
            return None
        try:
            f = float(v)
            return None if f != f else f
        except (ValueError, TypeError):
            return None

    def get_int(k: str) -> Optional[int]:
        v = raw.get(k)
        if v is None:
            return None
        try:
            return int(v)
        except (ValueError, TypeError):
            return None

    return {
        "symbol": ticker,
        "bid1Price": get_float("Best1Bid"),
        "bid1Quantity": get_int("Best1BidVolume"),
        "ask1Price": get_float("Best1Ask"),
        "ask1Quantity": get_int("Best1AskVolume"),
        "bid2Price": get_float("Best2Bid"),
        "bid2Quantity": get_int("Best2BidVolume"),
        "ask2Price": get_float("Best2Ask"),
        "ask2Quantity": get_int("Best2AskVolume"),
        "bid3Price": get_float("Best3Bid"),
        "bid3Quantity": get_int("Best3BidVolume"),
        "ask3Price": get_float("Best3Ask"),
        "ask3Quantity": get_int("Best3AskVolume"),
        "spread": get_float("Spread"),
        "spreadDelta": get_float("SpreadDelta"),
        "depthImbalance": get_float("DepthImbalance"),
        "totalBidVolume": get_int("TotalBidVolume"),
        "totalAskVolume": get_int("TotalAskVolume"),
        "providerTimestamp": provider_timestamp,
        "receivedTimestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
