"""Trade-only in-memory bar builder fed by the existing FiinQuant trade stream."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.market_data.providers.fiinquant_normalization import number, timestamp
from app.market_data.trading_calendar import VN_TZ

_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60}


class LiveBarBuilder:
    def __init__(self) -> None:
        self._bars: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._seen: set[tuple] = set()
        self._latest_ms: dict[str, int] = {}

    @staticmethod
    def _instant(raw: dict) -> datetime | None:
        normalized = timestamp(raw.get("TradingDate") or raw.get("Timestamp"))
        return datetime.fromisoformat(normalized) if normalized else None

    @staticmethod
    def _bucket(dt: datetime, minutes: int) -> datetime:
        local = dt.astimezone(VN_TZ).replace(second=0, microsecond=0)
        # Wall-clock buckets in exchange time. Lunch naturally remains a gap.
        since_midnight = local.hour * 60 + local.minute
        start = since_midnight - (since_midnight % minutes)
        return local.replace(hour=0, minute=0) + timedelta(minutes=start)

    def on_trade(self, symbol: str, raw: dict) -> list[dict[str, Any]]:
        price = number(raw, "Close", "MatchPrice", "Price")
        dt = self._instant(raw)
        if price is None or dt is None:
            return []
        source_ms = int(dt.timestamp() * 1000)
        if source_ms < self._latest_ms.get(symbol, 0):
            return []
        qty = number(raw, "MatchVolume", "TradedVolume")
        match_value = number(raw, "MatchValue")
        identity = (symbol, source_ms, price, qty, number(raw, "TotalMatchVolume"))
        if identity in self._seen:
            return []
        self._seen.add(identity)
        self._latest_ms[symbol] = source_ms
        if len(self._seen) > 20_000:
            self._seen.clear()
            self._seen.add(identity)

        patches: list[dict[str, Any]] = []
        for timeframe, minutes in _MINUTES.items():
            start = self._bucket(dt, minutes)
            key = (symbol, timeframe, start.isoformat())
            bar = self._bars.get(key)
            if bar is None:
                bar = {
                    "symbol": symbol, "date": start.isoformat(),
                    "open": price, "high": price, "low": price, "close": price,
                    "volume": qty, "value": match_value,
                    "price_basis": "RAW", "source": "FIINQUANT_TRADE_STREAM",
                    "session_date": start.date().isoformat(), "complete": False,
                }
                self._bars[key] = bar
            else:
                bar["high"] = max(bar["high"], price)
                bar["low"] = min(bar["low"], price)
                bar["close"] = price
                bar["volume"] = None if bar["volume"] is None or qty is None else bar["volume"] + qty
                bar["value"] = None if bar["value"] is None or match_value is None else bar["value"] + match_value
            patches.append({"type": "bar_patch", "symbol": symbol,
                            "timeframe": timeframe, "bar": dict(bar),
                            "ts": int(dt.timestamp() * 1000)})
        return patches


live_bar_builder = LiveBarBuilder()
