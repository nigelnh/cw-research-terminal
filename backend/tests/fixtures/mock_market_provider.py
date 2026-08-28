import asyncio
import logging
from typing import List, Dict, Any, Optional, Callable
from datetime import datetime, timezone

from app.market_data.market_schemas import HistoricalBar
from app.market_data.providers.base_market_provider import MarketDataProvider

logger = logging.getLogger(__name__)


class MockMarketDataProvider(MarketDataProvider):
    """
    In-memory mock provider for testing and offline local development.
    Simulates real-time ticks and EOD bars without external dependencies.
    """

    def __init__(self, max_symbols: int = 33):
        self.max_symbols = max_symbols
        self._active_symbols: List[str] = []
        self._is_connected = False
        self._event_callback: Optional[Callable[[str, Dict[str, Any], str], None]] = None

    def set_event_callback(self, callback: Callable[[str, Dict[str, Any], str], None]) -> None:
        self._event_callback = callback

    async def connect(self) -> bool:
        self._is_connected = True
        return True

    async def disconnect(self) -> None:
        self._is_connected = False
        self._active_symbols = []

    async def set_subscriptions(self, symbols: List[str]) -> bool:
        clean = list(dict.fromkeys([s.strip().upper() for s in symbols if s.strip()]))
        if len(clean) > self.max_symbols:
            return False
        self._active_symbols = clean
        return True

    def get_active_subscriptions(self) -> List[str]:
        return list(self._active_symbols)

    def get_health(self) -> Dict[str, Any]:
        if not self._is_connected:
            computed_status = "DISCONNECTED"
        elif not self._active_symbols:
            computed_status = "READY"
        else:
            computed_status = "LIVE"

        return {
            "provider": "mock",
            "authenticated": self._is_connected,
            "upstream_status": computed_status,
            "trade_stream_connected": self._is_connected and len(self._active_symbols) > 0,
            "bid_ask_stream_connected": self._is_connected and len(self._active_symbols) > 0,
            "subscription_count": len(self._active_symbols),
            "max_subscriptions": self.max_symbols,
            "subscriptions": self.get_active_subscriptions(),
        }

    async def get_historical_bars(
        self,
        symbol: str,
        timeframe: str = "1D",
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        adjusted: bool = True,
    ) -> List[HistoricalBar]:
        return [
            HistoricalBar(date="2026-08-20", open=22000, high=22500, low=21900, close=22300, volume=1000000),
            HistoricalBar(date="2026-08-21", open=22300, high=22400, low=22100, close=22200, volume=850000),
            HistoricalBar(date="2026-08-24", open=22200, high=22350, low=22150, close=22250, volume=1200000),
        ]

    def emit_mock_trade(self, symbol: str, match_price: float, volume: int = 1000) -> None:
        if self._event_callback:
            now_iso = datetime.now(timezone.utc).isoformat()
            self._event_callback(
                "trade",
                {
                    "Ticker": symbol.upper(),
                    "Close": match_price,
                    "TotalMatchVolume": volume,
                    "TradingDate": now_iso,
                    "Timestamp": now_iso,
                },
                symbol.upper(),
            )

    def emit_mock_bidask(self, symbol: str, bid1: float, ask1: float, bid_vol: int = 5000, ask_vol: int = 5000) -> None:
        if self._event_callback:
            now_iso = datetime.now(timezone.utc).isoformat()
            self._event_callback(
                "bidask",
                {
                    "Ticker": symbol.upper(),
                    "Best1Bid": bid1,
                    "Best1BidVolume": bid_vol,
                    "Best1Ask": ask1,
                    "Best1AskVolume": ask_vol,
                    "Timestamp": now_iso,
                },
                symbol.upper(),
            )
