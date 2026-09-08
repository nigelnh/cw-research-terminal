"""Canonical event helpers shared by every market-data transport.

Prices are raw VND (indices are points), quantities are units, and values are VND.
Timestamp strings without an offset are exchange-local, never the server's timezone.
"""
import math
from datetime import datetime
from typing import Any

from app.market_data.trading_calendar import VN_TZ


def first(row: dict, *keys: str) -> Any:
    return next((row[k] for k in keys if row.get(k) is not None), None)


def number(row: dict, *keys: str) -> float | None:
    for key in keys:
        value = row.get(key)
        if value is None or isinstance(value, bool):
            continue
        try:
            result = float(value)
            if math.isfinite(result):
                return result
        except (TypeError, ValueError):
            continue
    return None


def timestamp(value: Any) -> str | None:
    if value is None:
        return None
    try:
        dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=VN_TZ)
        return dt.astimezone(VN_TZ).isoformat()
    except (TypeError, ValueError):
        return None


def normalize_event(raw: dict) -> dict:
    row = dict(raw)
    aliases = {
        "Close": ("Close", "MatchPrice", "ClosePrice", "Price"),
        "Reference": ("Reference", "ReferencePrice", "RefPrice"),
        "CeilingPrice": ("CeilingPrice", "Ceiling", "Ceil"),
        "FloorPrice": ("FloorPrice", "Floor"),
        "MatchVolume": ("MatchVolume", "TradedVolume"),
        "TotalMatchVolume": ("TotalMatchVolume", "TotalVolume", "Total_Vol", "total_volume"),
        "TotalMatchValue": ("TotalMatchValue", "TotalValue"),
        "Open": ("Open", "OpenPrice"),
        "High": ("High", "HighPrice", "HighestPrice"),
        "Low": ("Low", "LowPrice", "LowestPrice"),
    }
    for canonical, keys in aliases.items():
        if any(key in row for key in keys):
            row[canonical] = number(row, *keys)
    for key in ("TradingDate", "Timestamp"):
        if key in row:
            row[key] = timestamp(row[key])
    if row.get("MarketStatus") is not None:
        row["MarketStatus"] = str(row["MarketStatus"])
    return row
