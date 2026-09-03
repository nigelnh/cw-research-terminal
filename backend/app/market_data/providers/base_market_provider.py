from abc import ABC, abstractmethod
from datetime import date
from typing import List, Dict, Any, Callable, Optional
from app.market_data.market_schemas import HistoricalBar


class MarketDataProvider(ABC):
    """
    Abstract interface for live market data and historical price providers.
    Decouples FastAPI and WebSocket layers from concrete vendor SDK implementations.
    """

    @abstractmethod
    async def connect(self) -> bool:
        """Establishes upstream session authentication and initial connectivity."""
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Gracefully disconnects and stops active stream connections."""
        pass

    @abstractmethod
    async def set_subscriptions(self, symbols: List[str]) -> bool:
        """
        Reconfigures the active streaming symbol set.
        For providers requiring stream recreation, stops and restarts streams cleanly.
        """
        pass

    @abstractmethod
    def get_active_subscriptions(self) -> List[str]:
        """Returns the current list of subscribed symbols."""
        pass

    @abstractmethod
    def get_health(self) -> Dict[str, Any]:
        """Returns sanitized operational health metrics."""
        pass

    @abstractmethod
    async def get_historical_bars(
        self,
        symbol: str,
        timeframe: str = "1D",
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        adjusted: bool = True,
    ) -> List[HistoricalBar]:
        """Fetches historical price bars for the given symbol."""
        pass

    @abstractmethod
    def set_event_callback(self, callback: Callable[[str, Dict[str, Any], str], None]) -> None:
        """
        Registers a callback for normalized live events.
        Signature: callback(event_type: 'trade' | 'bidask', data: dict, symbol: str)
        """
        pass

    async def get_market_overview(self, cw_symbols: List[str]) -> Dict[str, Any]:
        """Return a cached, read-only market overview when the vendor supports it."""
        raise NotImplementedError("market overview is not supported by this provider")

    async def get_stock_profiles(self, symbols: List[str]) -> List[Dict[str, Any]]:
        """Read company names and exchanges without streaming subscriptions."""
        raise NotImplementedError("stock profiles are not supported by this provider")

    async def get_session_reference_data(
        self, symbols: List[str], session_date: date
    ) -> Dict[str, Dict[str, Any]]:
        """Return raw-unit previous close and exchange bands for one session.

        This is deliberately separate from the streaming subscription interface: many
        vendor L1 feeds omit static reference/ceiling/floor fields from incremental events.
        """
        raise NotImplementedError("session reference data is not supported by this provider")
