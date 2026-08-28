"""
Abstract base class for Instrument Registry providers.
"""

from abc import ABC, abstractmethod
from typing import List, Optional
from app.instruments.instrument_schemas import CoveredWarrantSpecification


class InstrumentRegistryProvider(ABC):
    """Abstract interface for supplying Covered Warrant instrument specifications."""

    @abstractmethod
    async def load_instruments(self) -> List[CoveredWarrantSpecification]:
        """Loads and returns all instrument specifications."""
        pass

    @abstractmethod
    async def get_instrument(self, symbol: str) -> Optional[CoveredWarrantSpecification]:
        """Retrieves a single instrument specification by symbol."""
        pass
