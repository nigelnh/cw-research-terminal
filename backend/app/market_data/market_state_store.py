from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
import logging

from app.market_data.market_schemas import CanonicalQuote, HistoricalBar

logger = logging.getLogger(__name__)


class MarketStateStore(ABC):
    """
    Abstract interface for secondary warm market state caching.
    Provides non-authoritative persistence for the latest CanonicalQuote objects.
    """

    @abstractmethod
    async def initialize(self) -> None:
        """Initializes storage connections and background workers."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Gracefully shuts down storage connections and background flush tasks."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Returns True if the store is enabled, connected, and ready for operations."""
        pass

    @abstractmethod
    async def load(self, symbol: str) -> Optional[CanonicalQuote]:
        """Loads a single cached CanonicalQuote for the given symbol."""
        pass

    @abstractmethod
    async def load_many(self, symbols: List[str]) -> Dict[str, CanonicalQuote]:
        """Loads multiple cached CanonicalQuote objects for given symbols."""
        pass

    @abstractmethod
    async def save(self, symbol: str, quote: CanonicalQuote) -> None:
        """Directly persists a single CanonicalQuote."""
        pass

    @abstractmethod
    async def save_many(self, quotes: Dict[str, CanonicalQuote]) -> None:
        """Directly persists multiple CanonicalQuote objects in a batch."""
        pass

    @abstractmethod
    def enqueue_save(self, symbol: str, quote: CanonicalQuote) -> None:
        """
        Thread-safe non-blocking enqueue operation.
        Buffers latest quote for background coalesced writing without blocking event loop or callbacks.
        """
        pass

    async def load_dashboard_history(
        self, symbol: str, price_basis: str, session_date: str
    ) -> Optional[List[HistoricalBar]]:
        """Optional, separately-namespaced completed-session history cache."""
        return None

    async def save_dashboard_history(
        self, symbol: str, price_basis: str, session_date: str, bars: List[HistoricalBar]
    ) -> None:
        pass

    async def load_market_overview(self) -> Optional[Dict[str, Any]]:
        return None

    async def save_market_overview(self, payload: Dict[str, Any]) -> None:
        pass

    async def load_quant_analytics(
        self, symbols: List[str], session_date: str
    ) -> Dict[str, Dict[str, Any]]:
        """Optional session-scoped cache for derived CW analytics.

        Analytics stay separate from :class:`CanonicalQuote`: quote fields are observed
        market data, while IV/Greeks are calculations with their own input provenance.
        """
        return {}

    async def save_quant_analytics(
        self, symbol: str, session_date: str, payload: Dict[str, Any]
    ) -> None:
        pass

    @abstractmethod
    async def delete(self, symbol: str) -> None:
        """Removes a symbol from the cache."""
        pass

    @abstractmethod
    async def health(self) -> Dict[str, Any]:
        """Returns sanitized storage health diagnostics."""
        pass


class NullMarketStateStore(MarketStateStore):
    """
    No-op implementation of MarketStateStore used when Redis is disabled or unconfigured.
    Safely degrades to LIVE_WITHOUT_WARM_CACHE.
    """

    async def initialize(self) -> None:
        pass

    async def close(self) -> None:
        pass

    def is_available(self) -> bool:
        return False

    async def load(self, symbol: str) -> Optional[CanonicalQuote]:
        return None

    async def load_many(self, symbols: List[str]) -> Dict[str, CanonicalQuote]:
        return {}

    async def save(self, symbol: str, quote: CanonicalQuote) -> None:
        pass

    async def save_many(self, quotes: Dict[str, CanonicalQuote]) -> None:
        pass

    def enqueue_save(self, symbol: str, quote: CanonicalQuote) -> None:
        pass

    async def delete(self, symbol: str) -> None:
        pass

    async def health(self) -> Dict[str, Any]:
        return {
            "redis_enabled": False,
            "redis_connected": False,
            "market_cache_available": False,
            "mode": "NULL_STORE",
        }
