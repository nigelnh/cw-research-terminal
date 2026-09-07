"""Trade-only in-memory bar builder fed by the existing FiinQuant trade stream."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.market_data.providers.fiinquant_normalization import number, timestamp
from app.market_data.trading_calendar import VN_TZ

_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60}
# Matches the chart's `interval` string, which is how the browser store keys patches.
_DAILY_TIMEFRAME = "1D"


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
        if price is None or price <= 0 or dt is None:
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

        daily = self._daily_bar(symbol, raw, dt, price)
        if daily is not None:
            patches.append({"type": "bar_patch", "symbol": symbol,
                            "timeframe": _DAILY_TIMEFRAME, "bar": daily,
                            "ts": int(dt.timestamp() * 1000)})
        return patches

    def _daily_bar(
        self, symbol: str, raw: dict, dt: datetime, price: float
    ) -> dict[str, Any] | None:
        """Today's forming candle for the 1D chart.

        The panel chart is 1D, and only the intraday timeframes had a live bucket - so the
        newest candle was always yesterday's completed bar while the header showed a live
        price. This closes that gap.

        It prefers the session aggregates the trade frame already carries (Open/High/Low
        and the cumulative TotalMatchVolume / TotalMatchValue) over re-deriving them from
        the ticks we happened to observe: those are the exchange's own numbers, so the
        candle stays correct across a reconnect that made us miss part of the session.
        Anything the frame omits falls back to accumulating from what we have seen.

        `date` is the plain ICT session date, matching the REST daily bars, so the merge
        replaces today's row instead of appending a duplicate.
        """
        session = dt.astimezone(VN_TZ).date().isoformat()
        key = (symbol, _DAILY_TIMEFRAME, session)
        bar = self._bars.get(key)

        open_ = number(raw, "Open", "OpenPrice")
        high = number(raw, "High", "HighPrice", "HighestPrice")
        low = number(raw, "Low", "LowPrice", "LowestPrice")
        total_vol = number(raw, "TotalMatchVolume", "TotalVolume", "Total_Vol")
        total_val = number(raw, "TotalMatchValue", "TotalValue")

        if bar is None:
            bar = {
                "symbol": symbol, "date": session,
                "open": open_ if open_ and open_ > 0 else price,
                "high": high if high and high > 0 else price,
                "low": low if low and low > 0 else price,
                "close": price,
                "volume": total_vol, "value": total_val,
                "price_basis": "RAW", "source": "FIINQUANT_TRADE_STREAM",
                "session_date": session, "complete": False,
            }
            self._bars[key] = bar
        else:
            if open_ and open_ > 0:
                bar["open"] = open_
            # A provider high/low always wins; otherwise widen with the observed trade.
            bar["high"] = high if high and high > 0 else max(bar["high"], price)
            bar["low"] = low if low and low > 0 else min(bar["low"], price)
            bar["close"] = price
            # Cumulative totals are absolute, never summed.
            if total_vol is not None:
                bar["volume"] = total_vol
            if total_val is not None:
                bar["value"] = total_val
        return dict(bar)


live_bar_builder = LiveBarBuilder()
