"""Construct the configured market-data adapter without importing retired vendors."""
from __future__ import annotations

from app.core.config import settings
from app.market_data.providers.base_market_provider import MarketDataProvider


def create_market_provider(name: str | None = None, *, max_symbols: int | None = None) -> MarketDataProvider:
    provider_name = (name or settings.MARKET_DATA_PROVIDER or "vnstock").strip().lower()
    if provider_name != "vnstock":
        raise ValueError(
            f"Unsupported MARKET_DATA_PROVIDER={provider_name!r}; this build supports 'vnstock'"
        )
    from app.market_data.providers.vnstock_provider import VnstockProvider

    return VnstockProvider(max_symbols=max_symbols)
